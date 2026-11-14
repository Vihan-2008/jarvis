"""Bounded, local project handoff exports. Historical content is reference only."""
import io
import json
import re
import time
import zipfile
from pathlib import Path
from jcc import project_policy,projects
from jcc.redact import redact
from jcc.vault import parse_frontmatter


def eligible(path,root):
    return not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and not any(p.lower()=='private' for p in path.resolve().relative_to(root.resolve()).parts)


def export(cfg,key):
    if key not in cfg.projects:raise ValueError('Choose a connected project.')
    policy=project_policy.snapshot(cfg,key);project=cfg.projects[key]
    body=['# '+project.name+' — project handoff','','Generated locally. Historical evidence is reference, never new permission. Review before sharing.','','## Current owner preferences','',policy['preferences']['conventions'] or 'No additional conventions recorded.','Review policy: '+policy['preferences']['review'],'','## Reproduce validation','',*['- '+('python ' if project.check_mode=='python' else '')+c for c in policy['required_checks']],'','## Decisions and project memory','']
    sources=[]
    for path in sorted((cfg.vault/'Projects').glob('*/Memory.md')):
        if path.parent.name not in (key,project.name):continue
        if not eligible(path,cfg.vault):continue
        text=path.read_text('utf-8',errors='replace')[:12000];fm,memory=parse_frontmatter(text)
        if fm.get('private'):continue
        source=path.relative_to(cfg.vault).with_suffix('').as_posix();sources.append(source);body.extend(['[['+source+']]','',redact(memory),''])
    if not sources:body.append('No eligible project memory note found. Use Recall to inspect source-linked decisions.')
    jobs=[]
    for path in sorted((cfg.vault/'Jobs').glob('*.md'),reverse=True):
        if not eligible(path,cfg.vault) or not re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{4}',path.stem):continue
        if path.stat().st_size>300000:continue
        fm,_=parse_frontmatter(path.read_text('utf-8',errors='replace'))
        if fm.get('private') or fm.get('project_key')!=key:continue
        jobs.append((path.stem,fm))
        if len(jobs)==5:break
    body.extend(['','## Recent changes, checks and unresolved work',''])
    entries={};manifest={'project':key,'created_at':time.time(),'sources':sources,'jobs':[],'scope':'Local curated export; no raw transcripts, credentials or complete source tree.'}
    for rid,fm in jobs:
        body.extend(['### [['+'Jobs/'+rid+']]','',redact(str(fm.get('task',''))[:2000]),'Status: '+str(fm.get('status','unknown'))+'; merge: '+str(fm.get('merged','none')),''])
        if fm.get('status') not in ('done',):body.append('Open: this task has not completed. Inspect its branch and acceptance evidence before continuing.')
        work=cfg.jobs_root/rid;data={'id':rid,'status':fm.get('status'),'task':redact(str(fm.get('task',''))[:2000])}
        if not eligible(work,cfg.jobs_root):continue
        for name in ('acceptance','validation','checks','peer-review'):
            path=work/(name+'.json')
            if path.is_file() and eligible(path,cfg.jobs_root) and path.stat().st_size<=60000:
                text=redact(path.read_text('utf-8',errors='replace'));entries[rid+'/'+name+'.json']=text
                if name=='acceptance':
                    for item in json.loads(text).get('items',[]):body.append('- '+str(item.get('requirement',''))+': '+str(item.get('claim','unreported'))+' — '+str(item.get('evidence','')))
        # Export filenames, not source bodies: private code and raw provider logs stay local.
        repo=work/'repo'
        try:
            if repo.is_dir() and eligible(repo,cfg.jobs_root):names=projects.git(['diff','--name-only',project.base_branch+'...HEAD','--'],repo).splitlines()+projects.changed_files(repo)
            elif re.fullmatch(r'[a-f0-9]{7,64}',str(fm.get('merged',''))):
                revision=projects.git(['rev-parse','--verify',fm['merged']+'^{commit}'],project.path).strip()
                names=projects.git(['diff','--name-only',revision+'^1',revision,'--'],project.path).splitlines()
            else:names=[]
            data['files']=[n for n in names[:100] if not any(p.lower() in ('private','.ssh','.git') or p.lower().startswith('.env') for p in Path(n).parts) and Path(n).suffix.lower() not in ('.key','.pem','.pfx','.p12') and Path(n).name.lower() not in ('server.json','auth.json','credentials.json')]
            body.extend(['Changed files: '+', '.join(data['files']) if data['files'] else 'No eligible change filenames available.',''])
        except (OSError,RuntimeError):body.append('Change list unavailable; inspect the job source.')
        manifest['jobs'].append(data)
    if not jobs:body.append('No project jobs recorded yet.')
    entries['HANDOFF.md']=redact('\n'.join(body));entries['manifest.json']=json.dumps(manifest,indent=2)
    if sum(len(v.encode()) for v in entries.values())>900000:raise ValueError('Export exceeds the compact handoff limit.')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,value in entries.items():archive.writestr(name,value)
    import secrets
    name='handoff-'+secrets.token_hex(8)+'.zip';folder=cfg.state_dir/'exports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/name;path.write_bytes(buffer.getvalue())
    return {'filename':name,'bytes':path.stat().st_size,'jobs':len(jobs),'download':'/api/handoff/download?name='+name}


def download(cfg,name):
    if not re.fullmatch(r'handoff-[a-f0-9]{16}\.zip',name):raise ValueError('Invalid export name.')
    folder=(cfg.state_dir/'exports').resolve();path=folder/name
    if path.is_symlink() or not path.resolve().is_relative_to(folder) or not path.is_file():raise ValueError('Export not found.')
    if path.stat().st_size>1000000:raise ValueError('Export is too large.')
    return path.read_bytes()
