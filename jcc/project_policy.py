"""Owner-selected project conventions and additive validation requirements."""
import json
from dataclasses import replace
from jcc.lock import InstanceLock
from jcc.vault import atomic_write

CHECKS = {'compile': ['-m','compileall','-q','src'],
          'unittest': ['-m','unittest','discover','-s','tests'],
          'pytest': ['-m','pytest','-q']}
DEFAULT = {'conventions':'','checks':[],'review':'inherit'}


def read(cfg, key):
    if key not in cfg.projects: raise ValueError('Project not found.')
    path=cfg.state_dir/'project-policies.json'
    data=json.loads(path.read_text('utf-8')) if path.exists() else {}
    return {**DEFAULT,**data.get(key,{})}


def configure(cfg,key,value):
    read(cfg,key)
    if not isinstance(value,dict) or set(value)-set(DEFAULT): raise ValueError('Invalid project preferences.')
    value={**DEFAULT,**value}
    if not isinstance(value['conventions'],str) or len(value['conventions'])>4000: raise ValueError('Conventions must be at most 4,000 characters.')
    if not isinstance(value['checks'],list) or any(not isinstance(c,str) or c not in CHECKS for c in value['checks']): raise ValueError('Choose the supplied check types.')
    if value['review'] not in ('inherit','always','second_opinion'): raise ValueError('Unknown review policy.')
    if value['checks'] and cfg.projects[key].check_mode!='python': raise ValueError('Additional Python checks apply only to Python projects.')
    lock=InstanceLock(cfg.state_dir/'project-policies.lock')
    if not lock.acquire(): raise ValueError('Preferences are being saved. Try again.')
    try:
        path=cfg.state_dir/'project-policies.json';data=json.loads(path.read_text('utf-8')) if path.exists() else {}
        data[key]=value;atomic_write(path,json.dumps(data))
    finally: lock.release()
    return snapshot(cfg,key)


def effective(cfg,project):
    if project is None:return None
    policy=read(cfg,project.key);checks=[list(c) for c in project.checks]
    for key in policy['checks']:
        if CHECKS[key] not in checks:checks.append(CHECKS[key])
    return replace(project,checks=checks,auto_merge=project.auto_merge and policy['review']!='always')


def snapshot(cfg,key):
    project=effective(cfg,cfg.projects[key]);policy=read(cfg,key)
    return {'project':key,'preferences':policy,'required_checks':[' '.join(c) for c in project.checks],
            'check_options':list(CHECKS) if project.check_mode=='python' else [],'auto_merge':project.auto_merge}
