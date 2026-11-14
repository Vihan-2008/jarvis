"""Local memory inventory and bounded snapshot history; originals remain untouched."""
import hashlib
import json
import re
import time
from pathlib import Path
from jcc.privacy import note
from jcc.redact import redact
from jcc.vault import atomic_write


def describe(cfg,name):
    from jcc.vault import Vault
    value=Vault(cfg.vault).note_for_ai(name)
    if value is None:raise ValueError('Note not found.')
    fm=value.frontmatter;stamp=value.path.stat().st_mtime;age=max(0,(time.time()-stamp)/86400)
    signature=hashlib.sha256(value.path.read_bytes()).hexdigest()
    links=re.findall(r'\[\[([^\]|#]+)',value.body)[:20]
    return {'source':value.rel.removesuffix('.md'),'updated':stamp,'age_days':round(age,1),'review_due':age>90,
        'confidence':fm.get('confidence','unspecified'),'superseded_by':fm.get('superseded_by'),'links':links,
        'signature':signature,'scope':'A source link and modification date establish provenance, not factual correctness. Linked/private notes are not automatically expanded.'}


def audit(cfg):
    entries=[];changed=0;folder=cfg.state_dir/'memory-versions';manifest_path=folder/'manifest.json'
    previous=json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else {};current={}
    candidates=list((cfg.vault/'Projects').glob('*/Memory.md'))+list((cfg.vault/'Projects').glob('*/Recent work.md'))+list((cfg.vault/'System').glob('*.md'))
    for path in candidates[:250]:
        value=note(path,cfg.vault,limit=100000)
        if value is None:continue
        source=path.relative_to(cfg.vault).as_posix();fm,body=value;content=redact(body[:18000]);signature=hashlib.sha256(content.encode()).hexdigest();key=hashlib.sha256(source.encode()).hexdigest()[:24]
        history=list(previous.get(source,{}).get('versions',[]))
        if previous.get(source,{}).get('signature')!=signature:
            version=key+'-'+signature[:16]+'.json';atomic_write(folder/version,json.dumps({'source':source,'at':time.time(),'body':content,'signature':signature}));history=[*history,version][-12:];changed+=1
        current[source]={'signature':signature,'versions':history,'updated':path.stat().st_mtime}
        if fm.get('superseded_by') or time.time()-path.stat().st_mtime>90*86400:entries.append({'source':source.removesuffix('.md'),'superseded_by':fm.get('superseded_by'),'review_due':True})
    # Forget references to now-private/deleted notes; versions are never served without rechecking the source.
    atomic_write(manifest_path,json.dumps(current));result={'at':time.time(),'notes':len(current),'changed':changed,'review':entries[:50]};atomic_write(cfg.state_dir/'memory-freshness-status.json',json.dumps(result));return result


def versions(cfg,name):
    source=describe(cfg,name)['source']+'.md';folder=cfg.state_dir/'memory-versions';path=folder/'manifest.json'
    manifest=json.loads(path.read_text('utf-8')) if path.exists() else {};result=[]
    for version in manifest.get(source,{}).get('versions',[]):
        if not re.fullmatch(r'[a-f0-9]{24}-[a-f0-9]{16}\.json',version):continue
        file=folder/version
        if file.is_symlink() or not file.is_file():continue
        value=json.loads(file.read_text('utf-8'))
        if value.get('source')==source:result.append(value)
    return {'source':source,'versions':result,'scope':'Reference snapshots only. Original notes are never automatically restored or rewritten.'}
