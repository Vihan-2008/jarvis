"""Inspectable diffs and a checked revert commit; never discard user work."""
import json
import re
from pathlib import Path
from jcc import activity, projects, receipts, workspace, project_policy
from jcc.vault import Vault, atomic_write, parse_frontmatter, render_note
from jcc.redact import redact
from jcc.lock import InstanceLock


def note(cfg, rid):
    rid = activity.job_id(rid)
    text = Vault(cfg.vault).read(f'Jobs/{rid}.md')
    if not text: raise ValueError('Job not found.')
    return parse_frontmatter(text)[0]


def details(cfg, rid):
    fm = note(cfg,rid); workspace.refresh(cfg)
    project = cfg.projects.get(fm.get('project_key'))
    work = cfg.jobs_root/rid; repo = work/'repo'
    patch, files = '', []
    untracked=[]
    if project:
        if repo.exists():
            root = repo; args = [project.base_branch]
            untracked=projects.git(['ls-files','--others','--exclude-standard','-z'],repo).split('\0')
        elif fm.get('merged'):
            root = project.path; revision = projects.git(['rev-parse','--verify',fm['merged']+'^{commit}'],root).strip()
            args = [revision+'^1',revision]
        else: root = None
        if root:
            names = projects.git(['diff','--name-only','-z',*args,'--'],root).split('\0')+untracked
            for name in names[:40]:
                if not name: continue
                parts = Path(name).parts
                if any(p in ('.env','.ssh','.git') or p.startswith('.env.') for p in parts) or Path(name).suffix.lower() in ('.pem','.key','.pfx','.p12') or Path(name).name in ('server.json','auth.json','credentials.json'):
                    continue
                path=root/name
                from jcc.privacy import safe_path,note as safe_note
                if not safe_path(path,root) or path.suffix.lower()=='.md' and path.exists() and safe_note(path,root,explicit=True) is None:continue
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()): continue
                files.append(name)
                if name in untracked:
                    if path.is_file() and path.stat().st_size<=100000:
                        patch+='New file: '+name+'\n'+path.read_text('utf-8',errors='replace')[:10000]+'\n'
                else: patch += projects.git(['diff',*args,'--',name],root)[-10000:]+'\n'
                if len(patch)>60000: break
    metrics = json.loads((work/'metrics.json').read_text('utf-8')) if (work/'metrics.json').exists() else None
    can_undo=False
    if project and fm.get('merged') and not fm.get('undone_by') and re.fullmatch(r'[a-f0-9]{7,64}',str(fm['merged'])):
        can_undo=(projects.git(['rev-parse','HEAD'],project.path).strip()==projects.git(['rev-parse','--verify',fm['merged']+'^{commit}'],project.path).strip()
            and not projects.git(['status','--porcelain'],project.path).strip()
            and projects.git(['branch','--show-current'],project.path).strip()==project.base_branch)
    return {'id':rid,'task':fm.get('task'),'status':fm.get('status'),'reason':fm.get('routing_reason'),
        'events':activity.events(cfg,rid),'files':files,'diff':redact(patch[:60000]),'metrics':metrics,
        'can_undo':can_undo,'acceptance':json.loads((work/'acceptance.json').read_text('utf-8')) if (work/'acceptance.json').exists() else None,
        'peer_review':json.loads((work/'peer-review.json').read_text('utf-8')) if (work/'peer-review.json').exists() else None,
        'revision':projects.git(['rev-parse','HEAD'],repo).strip() if repo.exists() and project else None,
        'can_merge':bool(project and repo.exists() and fm.get('status') == 'needs_approval' and not fm.get('blocked_by'))}


def approve(cfg, rid, expected):
    fm=note(cfg,rid);workspace.refresh(cfg);proj=project_policy.effective(cfg,cfg.projects.get(fm.get('project_key')));repo=cfg.jobs_root/rid/'repo'
    if not proj or not repo.is_dir() or fm.get('status')!='needs_approval': raise ValueError('This branch is not awaiting review.')
    lock=InstanceLock(cfg.jobs_root/rid/'job.lock')
    if not lock.acquire(): raise ValueError('The job is still running.')
    try:
        if projects.git(['branch','--show-current'],repo).strip()!=projects.branch_name(rid): raise ValueError('Unexpected branch; merge refused.')
        if projects.git(['rev-parse','HEAD'],repo).strip()!=expected: raise ValueError('Changes have moved since the preview. Refresh and review again.')
        names=projects.git(['diff','--name-only',proj.base_branch+'...HEAD'],repo).splitlines()
        if projects.blocked_paths(names,proj.no_auto_merge): raise ValueError('Protected files cannot be merged through automatic approval.')
        import os
        from jcc.jobs import scrub_env
        checks=projects.run_checks(proj,repo,scrub_env(dict(os.environ)),timeout_s=300)
        if not checks or not all(c.ok for c in checks): raise ValueError('Checks did not pass; branch retained for review.')
        if projects.changed_files(repo): raise ValueError('The reviewed branch has uncommitted changes; review it again before merging.')
        ok,message=projects.merge(proj,rid)
        if not ok: raise ValueError(message)
        fm.update({'status':'done','merged':message,'checks_passed':True})
        acceptance_path=cfg.jobs_root/rid/'acceptance.json'
        if acceptance_path.exists():
            import time
            accepted=json.loads(acceptance_path.read_text('utf-8'));accepted.update({'owner_approved_at':time.time(),'needs_review':False})
            atomic_write(acceptance_path,json.dumps(accepted))
        vault=Vault(cfg.vault);_,body=parse_frontmatter(vault.read(f'Jobs/{rid}.md'))
        vault.write(f'Jobs/{rid}.md',render_note(fm,body+'\n\nReviewed and merged with passing checks.'))
        projects.remove_worktree(proj,repo,rid,True)
        receipts.update_status(vault,rid,'done',append='Reviewed and merged with passing checks.')
        if fm.get('chat_id'):
            from jcc.chats import Chats
            Chats(cfg).update(fm['chat_id'],message={'role':'assistant','receipt':rid,'status':'done','content':f'Reviewed changes passed checks and were merged.\n\n[[Jobs/{rid}|Job details]]'})
        path=cfg.jobs_root/rid/'metrics.json'
        if path.exists():
            metrics=json.loads(path.read_text('utf-8'));metrics.update({'status':'done','checks_passed':True});atomic_write(path,json.dumps(metrics))
        activity.emit(cfg,rid,'merged','Owner reviewed the changes; independent checks passed and the branch was merged.')
        activity.alert(cfg,rid,'done')
        return {'status':'done','commit':message}
    finally: lock.release()


def undo(cfg, rid):
    fm=note(cfg,rid);workspace.refresh(cfg);proj=project_policy.effective(cfg,cfg.projects.get(fm.get('project_key')))
    if not proj or not fm.get('merged') or fm.get('undone_by'): raise ValueError('This job has no merge available to undo.')
    lock=InstanceLock(cfg.state_dir/'undo.lock')
    if not lock.acquire(): raise ValueError('An undo is already running.')
    new_id=receipts.new_id();work=cfg.jobs_root/new_id;repo=work/'repo';vault=Vault(cfg.vault)
    created=False
    try:
        current=projects.git(['rev-parse','HEAD'],proj.path).strip()
        target=projects.git(['rev-parse','--verify',fm['merged']+'^{commit}'],proj.path).strip()
        if current!=target or projects.git(['status','--porcelain'],proj.path).strip():
            raise ValueError('Undo is available only while that merge is the latest commit and the project is clean. Later work is preserved.')
        if projects.git(['branch','--show-current'],proj.path).strip()!=proj.base_branch:
            raise ValueError('Switch the project to its configured base branch before undoing.')
        work.mkdir(parents=True,exist_ok=True)
        projects.create_worktree(proj,repo,new_id);created=True
        projects.git(['revert','--no-commit','-m','1',target],repo)
        files=projects.changed_files(repo)
        if projects.blocked_paths(files,proj.no_auto_merge): raise ValueError('Protected files require manual review; no undo was merged.')
        import os
        from jcc.jobs import scrub_env
        checks=projects.run_checks(proj,repo,scrub_env(dict(os.environ)),timeout_s=300)
        atomic_write(work/'checks.json',json.dumps([c.__dict__ for c in checks]))
        if not checks or not all(c.ok for c in checks): raise ValueError('Undo checks failed. Original project is unchanged; the undo branch is retained for review.')
        projects.commit_all(repo,f'Undo JARVIS job {rid}')
        ok,message=projects.merge(proj,new_id)
        if not ok: raise ValueError('Undo not merged: '+message)
        fm['undone_by']=new_id
        _,body=parse_frontmatter(vault.read(f'Jobs/{rid}.md'))
        vault.write(f'Jobs/{rid}.md',render_note(fm,body+f'\n\nUndone safely by [[Jobs/{new_id}]].'))
        vault.write(f'Jobs/{new_id}.md',render_note({'id':new_id,'status':'done','kind':'undo','project_key':proj.key,'merged':message},f'# Undo completed\n\nReverted [[Jobs/{rid}]] with passing checks.\n'))
        projects.remove_worktree(proj,repo,new_id,True);created=False
        return {'status':'done','id':new_id,'commit':message}
    except Exception as e:
        if created:
            vault.write(f'Jobs/{new_id}.md',render_note({'id':new_id,'status':'needs_approval','kind':'undo','project_key':proj.key},'# Undo retained for review\n\n'+redact(str(e))))
        raise
    finally: lock.release()
