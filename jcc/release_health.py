"""Local release integrity and explicit settings schema compatibility."""
import hashlib
import json
import time
from pathlib import Path
from jcc.vault import atomic_write

SCHEMA=1


def initialize(cfg):
    path=cfg.state_dir/'settings-schema.json'
    current=json.loads(path.read_text('utf-8')) if path.exists() else {}
    if current.get('schema',0)>SCHEMA:raise ValueError('These settings require a newer JARVIS version. Preserve the current files and use a compatible application backup.')
    if current.get('schema')!=SCHEMA:
        from jcc.restorepoints import create
        point=create(cfg,'Before settings schema initialization')
        atomic_write(path,json.dumps({'schema':SCHEMA,'at':time.time(),'previous':current.get('schema',0),'restore_point':point['id']}))


def status(cfg):
    path=cfg.state_dir/'release-status.json'
    if not path.exists():return {'status':'unrecorded','scope':'No release integrity manifest recorded yet.'}
    value=json.loads(path.read_text('utf-8'));root=Path(__file__).resolve().parents[1];changed=[]
    for name,expected in value.get('files',{}).items():
        file=root/name
        if not name.startswith('jcc/') or file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):continue
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:changed.append(name)
    return {'status':'source changed' if changed else 'verified','at':value.get('at'),'backup':value.get('backup'),'changed':changed[:30],
        'scope':'Installed source checksums only. Changed source can be intentional; rerun fixed evaluations. The application backup and settings snapshots are separate recovery paths.'}
