"""Versioned non-secret settings snapshots, previewed restoration and rollback."""
import hashlib
import io
import json
import re
import secrets
import time
import zipfile
from jcc.lock import InstanceLock
from jcc.redact import redact
from jcc.vault import atomic_write

FILES={'efficiency.json','assistant-settings.json','delivery-settings.json','project-policies.json','routing.json','resources.json','budgets.json','task-queue.json','library.json','prompt-preferences.json','operations-preferences.json'}
SCHEMA=1


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def read(cfg,identity):
    if not isinstance(identity,str) or not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{8}',identity):raise ValueError('Invalid restore point.')
    folder=(cfg.state_dir/'restore-points').resolve();path=folder/(identity+'.json')
    if path.is_symlink() or not path.resolve().is_relative_to(folder) or not path.is_file() or path.stat().st_size>1500000:raise ValueError('Restore point not found or too large.')
    value=json.loads(path.read_text('utf-8'))
    if value.get('schema')!=SCHEMA or not isinstance(value.get('files'),dict) or set(value['files'])-FILES:raise ValueError('Unsupported settings snapshot.')
    for name,row in value['files'].items():
        if set(row)!={'content','sha256'} or not isinstance(row['content'],str) or digest(row['content'])!=row['sha256'] or len(row['content'])>200000:raise ValueError('Snapshot checksum failed.')
        if not isinstance(json.loads(row['content']),dict):raise ValueError('Snapshot settings must be objects.')
    return value


def create(cfg,label='Manual restore point'):
    files={}
    for name in sorted(FILES):
        path=cfg.state_dir/name
        if path.is_file() and not path.is_symlink() and path.stat().st_size<=200000:
            content=redact(path.read_text('utf-8'));json.loads(content);files[name]={'content':content,'sha256':digest(content)}
    identity=time.strftime('%Y%m%d-%H%M%S-')+secrets.token_hex(4)
    value={'schema':SCHEMA,'id':identity,'at':time.time(),'label':str(label)[:100],'files':files}
    atomic_write(cfg.state_dir/'restore-points'/(identity+'.json'),json.dumps(value))
    verified=read(cfg,identity)
    return {'id':identity,'at':value['at'],'label':value['label'],'files':len(verified['files']),'verified':True}


def listing(cfg):
    result=[]
    for path in sorted((cfg.state_dir/'restore-points').glob('*.json'),reverse=True)[:40]:
        try:
            value=read(cfg,path.stem);result.append({'id':value['id'],'at':value['at'],'label':value['label'],'files':len(value['files']),'verified':True})
        except (ValueError,OSError,KeyError):continue
    return result


def preview(cfg,identity):
    value=read(cfg,identity);changes=[];fingerprint=[]
    for name,row in value['files'].items():
        path=cfg.state_dir/name
        if path.is_symlink():raise ValueError('Settings path cannot be a symlink.')
        current=path.read_text('utf-8') if path.exists() else None
        signature=digest(current) if current is not None else None;fingerprint.append([name,signature,row['sha256']])
        if current!=row['content']:changes.append(name)
    version=digest(json.dumps(fingerprint,sort_keys=True))
    return {'id':identity,'version':version,'changes':changes,'scope':'Only listed non-secret preferences are restored. Credentials, chats, notes, repositories and jobs are untouched. Preferences absent from this snapshot are kept.'}


def validate(cfg,value):
    """Run current validators against an isolated copy before touching live preferences."""
    import tempfile
    from dataclasses import replace
    from pathlib import Path
    from jcc import efficiency,learning,delivery,governor,budgets,prompt_preferences,project_policy
    validators={'efficiency.json':efficiency.save,'assistant-settings.json':learning.configure,'delivery-settings.json':delivery.configure,'resources.json':governor.configure,'budgets.json':budgets.configure,'prompt-preferences.json':prompt_preferences.configure}
    with tempfile.TemporaryDirectory(prefix='jarvis-settings-check-') as folder:
        isolated=replace(cfg,state_dir=Path(folder))
        for name,row in value['files'].items():
            settings=json.loads(row['content'])
            if name in validators:
                defaults={'resources.json':governor.DEFAULTS,'budgets.json':budgets.DEFAULTS,'prompt-preferences.json':prompt_preferences.DEFAULTS}.get(name,{})
                validators[name](isolated,{**defaults,**settings})
            elif name=='project-policies.json':
                for key,prefs in settings.items():
                    if key in cfg.projects:project_policy.configure(isolated,key,prefs)
            elif name=='routing.json':
                from jcc.models import validate as model_validate
                if set(settings)-{'small','medium','large'}:raise ValueError('Unknown task-size routing preferences.')
                for prefs in settings.values():
                    if not isinstance(prefs,dict):raise ValueError('Invalid routing preferences.')
                    model_validate(cfg,prefs.get('model','auto'),prefs.get('effort','auto'))


def apply(cfg,identity,version):
    lock=InstanceLock(cfg.state_dir/'restore-points.lock')
    if not lock.acquire():raise ValueError('Settings recovery is already running.')
    previous={}
    try:
        plan=preview(cfg,identity)
        if plan['version']!=version:raise ValueError('Settings changed since preview. Preview again before restoring.')
        value=read(cfg,identity);validate(cfg,value);backup=create(cfg,'Before settings restore')
        for name in plan['changes']:
            path=cfg.state_dir/name;previous[name]=path.read_text('utf-8') if path.exists() else None
            atomic_write(path,value['files'][name]['content'])
        if 'routing.json' in plan['changes']:
            from jcc.routing import save
            save(cfg,json.loads(value['files']['routing.json']['content']))
        atomic_write(cfg.state_dir/'settings-recovery-status.json',json.dumps({'at':time.time(),'status':'restored','id':identity,'backup':backup['id'],'files':plan['changes']}))
        return {'status':'restored','files':plan['changes'],'backup':backup['id']}
    except Exception:
        for name,content in previous.items():
            if content is not None:atomic_write(cfg.state_dir/name,content)
            else:(cfg.state_dir/name).unlink(missing_ok=True)
        raise
    finally:lock.release()


def portable(cfg,identity):
    value=read(cfg,identity);buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps({k:v for k,v in value.items() if k!='files'},indent=2))
        for name,row in value['files'].items():archive.writestr('settings/'+name,row['content'])
        archive.writestr('README.md','# JARVIS settings backup\n\nNon-secret preferences only. Account credentials, vault notes, repositories and job workspaces need their own backups.\n')
    return buffer.getvalue()
