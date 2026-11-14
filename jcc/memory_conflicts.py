"""Source-linked conflicts in explicitly structured decisions; no inference calls."""
import hashlib
import json
import re
import time
from pathlib import Path
from jcc.vault import atomic_write,parse_frontmatter


def decisions(rel,fm,body):
    scope=rel.split('/')[1] if rel.startswith('Projects/') and len(rel.split('/'))>2 else 'general'
    pairs=[]
    if fm.get('decision_key') and fm.get('decision_value') is not None:pairs.append((str(fm['decision_key']),str(fm['decision_value'])))
    for section in re.findall(r'(?ims)^## (?:Decisions|Requirements and decisions)\s*\n(.*?)(?=^## |\Z)',body):
        pairs.extend(re.findall(r'(?m)^[-*] ([\w .-]{2,70}): ([^\n]{1,400})$',section))
    result=[]
    for key,value in pairs:
        key=re.sub(r'\s+',' ',key.strip().lower());value=value.strip()
        if re.search(r'secret|password|token|api.?key|credential',key):continue
        identity=hashlib.sha256((scope+'\0'+key).encode()).hexdigest()[:20]
        version=hashlib.sha256(value.encode()).hexdigest()
        result.append({'id':identity,'scope':scope,'key':key,'source':rel.removesuffix('.md'),'value':value,'version':version})
    return result


def read_source(cfg,source):
    if not isinstance(source,str):raise ValueError('Choose a note source.')
    rel=Path(source+'.md');path=(cfg.vault/rel).resolve()
    if rel.is_absolute() or not path.is_relative_to(cfg.vault.resolve()) or any(p.startswith('.') or p.lower()=='private' for p in rel.parts) or (cfg.vault/rel).is_symlink():raise ValueError('This source cannot be used.')
    if any(p.lower()=='private' for p in path.relative_to(cfg.vault.resolve()).parts):raise ValueError('Private notes cannot be decision sources.')
    if not path.is_file() or path.stat().st_size>500000:raise ValueError('Source note is unavailable.')
    fm,body=parse_frontmatter(path.read_text('utf-8'))
    if fm.get('private'):raise ValueError('Private notes cannot be decision sources.')
    return decisions(rel.as_posix(),fm,body)


def choices(cfg):
    path=cfg.state_dir/'memory-authority.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else {}


def scan(cfg,notes):
    groups={}
    for rel,fm,body,_ in notes:
        for row in decisions(rel,fm,body):groups.setdefault(row['id'],[]).append(row)
    prefs=choices(cfg);conflicts=[]
    for identity,rows in groups.items():
        if len({r['value'].casefold() for r in rows})<2:continue
        selected=prefs.get(identity)
        valid=selected and any(r['source']==selected['source'] and r['version']==selected['version'] for r in rows)
        conflicts.append({'id':identity,'key':rows[0]['key'],'scope':rows[0]['scope'],'sources':rows[:12],
            'selected':selected if valid else None,'status':'owner-selected source' if valid else 'review needed'})
    value={'at':time.time(),'conflicts':conflicts[:40], 'scope':'Structured decision fields and Decisions sections only. Different values are potential conflicts, not a semantic proof of contradiction.'}
    atomic_write(cfg.state_dir/'memory-conflicts.json',json.dumps(value));return value


def resolve(cfg,identity,source,version):
    rows=read_source(cfg,source)
    row=next((r for r in rows if r['id']==identity and r['version']==version),None)
    if not row:raise ValueError('Decision changed since the preview. Run the memory audit again.')
    from jcc.lock import InstanceLock
    lock=InstanceLock(cfg.state_dir/'memory-authority.lock')
    if not lock.acquire():raise ValueError('A decision preference is being saved. Try again.')
    try:
        prefs=choices(cfg);prefs[identity]={'source':source,'version':version}
        atomic_write(cfg.state_dir/'memory-authority.json',json.dumps(prefs))
    finally:lock.release()
    return {'status':'saved','source':source}


def context(cfg,project):
    blocks=[]
    for identity,selected in choices(cfg).items():
        try:rows=read_source(cfg,selected['source'])
        except (ValueError,OSError):continue
        for row in rows:
            if row['id']==identity and row['version']==selected['version'] and row['scope'] in ('general',project):
                blocks.append(f"Source: [[{row['source']}]]\nOwner-selected decision: {row['key']}: {row['value']}\nOther historical values for this decision may be outdated.")
    return blocks[:5]


def snapshot(cfg):
    path=cfg.state_dir/'memory-conflicts.json'
    result=json.loads(path.read_text('utf-8')) if path.exists() else {'conflicts':[]}
    prefs=choices(cfg)
    for item in result['conflicts']:
        current=[]
        for row in item['sources']:
            try:valid=any(r['id']==row['id'] and r['version']==row['version'] for r in read_source(cfg,row['source']))
            except (ValueError,OSError):valid=False
            if valid:current.append(row)
        item['sources']=current
        selected=prefs.get(item['id']);valid=selected and any(r['source']==selected['source'] and r['version']==selected['version'] for r in item['sources'])
        item['selected']=selected if valid else None
    result['conflicts']=[item for item in result['conflicts'] if len({r['value'].casefold() for r in item['sources']})>1]
    return result
