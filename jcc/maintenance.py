"""Local memory suggestions and periodic isolated GitHub recovery checks."""
import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path
from jcc.vault import Vault, atomic_write, parse_frontmatter
from jcc.redact import redact
from jcc.lock import InstanceLock


def memory_audit(cfg):
    notes=[];groups={};suggestions=[]
    for path in cfg.vault.rglob('*.md'):
        rel=path.relative_to(cfg.vault).as_posix()
        if any(p.startswith('.') or p.lower()=='private' for p in path.relative_to(cfg.vault).parts) or path.is_symlink(): continue
        if not path.resolve().is_relative_to(cfg.vault.resolve()) or rel.startswith(('Conversations/','Requests/','Jobs/')) or '/Jobs/' in rel or rel=='System/Memory audit.md': continue
        fm,body=parse_frontmatter(path.read_text('utf-8',errors='replace'))
        if fm.get('private'): continue
        notes.append((rel,fm,body,path.stat().st_mtime))
        if len(body.strip())>80: groups.setdefault(hashlib.sha256(body.strip().encode()).hexdigest(),[]).append(rel)
    all_names={p.relative_to(cfg.vault).with_suffix('').as_posix() for p in cfg.vault.rglob('*.md') if not any(x.startswith('.') for x in p.relative_to(cfg.vault).parts)}
    names={rel.removesuffix('.md') for rel,_,_,_ in notes}
    for paths in groups.values():
        if len(paths)>1: suggestions.append({'kind':'duplicate','sources':paths,'suggestion':'Identical note bodies. Review both sources and consider one canonical note with links; no notes were removed.'})
    for rel,fm,body,stamp in notes:
        due=False
        if fm.get('review_after'):
            try: due=date.fromisoformat(str(fm['review_after'])[:10])<date.today()
            except ValueError: pass
        if due or time.time()-stamp>90*86400:
            suggestions.append({'kind':'review due','sources':[rel],'suggestion':'Review this note against its linked sources. Age is a review signal, not proof that a fact is wrong.'})
        for target in set(re.findall(r'\[\[([^\]|#]+)',body)):
            target=target.strip().removesuffix('.md')
            if target in ('Note Name',) or target in all_names or any(n.rsplit('/',1)[-1]==target for n in all_names): continue
            matches=difflib.get_close_matches(target,list(names),n=1,cutoff=.75)
            suggestions.append({'kind':'unresolved link','sources':[rel], 'suggestion':'Check [['+target+']].'+(' Possible intended source: [['+matches[0]+']].' if matches else '')})
    from jcc.memory_conflicts import scan
    conflicts=scan(cfg,notes)
    for conflict in conflicts['conflicts']:
        suggestions.append({'kind':'potential decision conflict','sources':[r['source']+'.md' for r in conflict['sources']],
            'suggestion':conflict['key']+': different recorded values. Choose an authoritative source in JARVIS Memory settings; original notes stay unchanged.'})
    suggestions=suggestions[:100]
    result={'at':time.time(),'status':'review available' if suggestions else 'clean','notes_checked':len(notes),'suggestions':suggestions}
    atomic_write(cfg.state_dir/'memory-audit-status.json',json.dumps(result))
    body=['# Memory review suggestions','','This local audit does not rewrite, merge or delete notes. Historical conversations are preserved.','']
    for s in suggestions:
        body+=['- **'+s['kind']+'**: '+', '.join('[['+p.removesuffix('.md')+']]' for p in s['sources'])+' — '+s['suggestion']]
    if not suggestions: body+=['No duplicate bodies, overdue reviews or unresolved links were found in the inspected knowledge notes.']
    Vault(cfg.vault).write('System/Memory audit.md','\n'.join(body))
    return result


def restore_check(cfg, remote=None):
    config=cfg.state_dir/'github.json'
    if remote is None:
        if not config.exists(): return {'status':'not configured'}
        remote=json.loads(config.read_text('utf-8'))['remote']
        if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git',remote): raise ValueError('Unexpected backup remote.')
    lock=InstanceLock(cfg.state_dir/'restore-check.lock')
    if not lock.acquire(): return {'status':'checking'}
    status_path=cfg.state_dir/'restore-check-status.json'
    atomic_write(status_path,json.dumps({'at':time.time(),'status':'checking'}))
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'}
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    def git(root,*args,input=None):
        p=subprocess.run(['git','-C',str(root),*args],input=input,capture_output=True,env=env,timeout=180,creationflags=flags)
        if p.returncode: raise ValueError('Backup verification Git operation failed: '+redact(p.stderr.decode('utf-8',errors='replace'))[-240:])
        return p.stdout
    try:
        parent=(cfg.state_dir/'restore-checks').resolve();parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='verify-',dir=parent) as temp:
            # Verify the cleanup target before TemporaryDirectory can remove it.
            temp=Path(temp).resolve()
            if temp.parent!=parent: raise ValueError('Unexpected recovery folder.')
            objects=temp/'objects';snapshot=temp/'restored';snapshot.mkdir()
            git(temp,'clone','--bare','--depth','1',remote,str(objects))
            git(objects,'fsck','--full','--no-reflogs')
            head=git(objects,'rev-parse','HEAD').decode().strip()
            format=git(objects,'rev-parse','--show-object-format').decode().strip()
            entries=[]
            for entry in git(objects,'ls-tree','-r','-z','HEAD').split(b'\0'):
                if not entry: continue
                meta,name=entry.split(b'\t',1);mode,kind,oid=meta.decode().split();name=name.decode('utf-8')
                dest=(snapshot/name).resolve()
                if mode not in ('100644','100755') or kind!='blob' or not dest.is_relative_to(snapshot): raise ValueError('Backup contains an unsupported or unsafe file path.')
                entries.append((name,oid,dest))
            if not entries: raise ValueError('Backup contains no files.')
            payload=('\n'.join(e[1] for e in entries)+'\n').encode()
            blobs=git(objects,'cat-file','--batch',input=payload);pos=0;total=0;notes=0
            if len(blobs)>100_000_000: raise ValueError('Backup exceeds the automatic recovery-check size limit.')
            for name,oid,dest in entries:
                end=blobs.index(b'\n',pos);header=blobs[pos:end].decode().split();size=int(header[2]);pos=end+1
                content=blobs[pos:pos+size];pos+=size+1
                if header[:2]!=[oid,'blob'] or len(content)!=size: raise ValueError('Backup blob is incomplete.')
                digest=hashlib.new(format,b'blob '+str(size).encode()+b'\0'+content).hexdigest()
                if digest!=oid: raise ValueError('Backup blob checksum differs.')
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content)
                if dest.read_bytes()!=content: raise ValueError('Restored file differs from backup.')
                total+=size;notes+=name.endswith('.md')
            if not notes: raise ValueError('No Markdown notes were restored.')
            result={'at':time.time(),'status':'verified','commit':head,'files_restored':len(entries),'notes_restored':notes,'bytes':total,
                    'method':'Fresh clone, Git object checks, isolated file restoration and byte verification; no repository code executed.'}
    except Exception as e:
        result={'at':time.time(),'status':'error','error':redact(str(e))[:300]}
    finally: lock.release()
    atomic_write(status_path,json.dumps(result))
    return result


def main():
    from jcc.config import load
    cfg=load();lock=InstanceLock(cfg.state_dir/'maintenance.lock')
    if not lock.acquire(): return
    try:
        while True:
            try:
                from jcc.resilience import recover
                recover(cfg)
                from jcc.diagnostics import read
                from jcc import governor,provenance
                if governor.reason(cfg):
                    time.sleep(30);continue
                from jcc.evaluations import after_update
                after_update(cfg)
                freshness=read(cfg,'memory-freshness') or {}
                if time.time()-freshness.get('at',0)>3600:provenance.audit(cfg)
                governor.cleanup(cfg)
                audit=read(cfg,'memory-audit') or {}
                if time.time()-audit.get('at',0)>86400: memory_audit(cfg)
                backup=read(cfg,'restore-check') or {}
                period=7*86400 if backup.get('status')=='verified' else 300 if backup.get('status')=='checking' else 86400
                if time.time()-backup.get('at',0)>period and not governor.reason(cfg,network=True):
                    result=restore_check(cfg)
                    if result.get('status')=='error':
                        atomic_write(cfg.state_dir/'maintenance-error.json',json.dumps(result))
            except Exception as e:
                atomic_write(cfg.state_dir/'maintenance-error.json',json.dumps({'at':time.time(),'error':redact(str(e))[:200]}))
            time.sleep(60)
    finally: lock.release()


if __name__=='__main__': main()
