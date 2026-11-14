"""Withdraw deteriorating learned preferences without overriding manual routes."""
import hashlib
import json
import time
from jcc.vault import atomic_write


def apply(cfg,buckets,stats,efforts):
    path=cfg.state_dir/'routing-rollback.json'
    saved=json.loads(path.read_text('utf-8')) if path.exists() else {}
    now=time.time()
    for table,by_effort in ((stats,False),(efforts,True)):
        for row in table:
            key=(row['family'],row['level'],row['provider'],row['model'])
            records=buckets.get(key,[])
            if by_effort:records=[r for r in records if r['effort']==row['effort']]
            jobs={}
            for r in sorted(records,key=lambda r:r['at'],reverse=True):jobs.setdefault(r['id'],[]).append(r)
            recent=list(jobs.items())[:5]
            bad=[rid for rid,runs in recent if not all(r['ok'] for r in runs)]
            identity=hashlib.sha256(json.dumps([*key,row.get('effort') if by_effort else None]).encode()).hexdigest()[:24]
            fingerprint=hashlib.sha256(json.dumps(sorted(bad)).encode()).hexdigest()
            previous=saved.get(identity,{})
            if len(recent)>=5 and len(bad)>=2 and previous.get('fingerprint')!=fingerprint:
                saved[identity]={'fingerprint':fingerprint,'until':now+7*86400,
                    'reason':'At least two of the latest five qualifying tasks needed repair or negative feedback. Learned preference withdrawn for seven days.',
                    'family':key[0],'level':key[1],'provider':key[2],'model':key[3],'effort':row.get('effort') if by_effort else None,'jobs':[rid for rid,_ in recent]}
            value=saved.get(identity,{})
            if value.get('until',0)>now:
                row.update({'eligible':False,'suspended_until':value['until'],'rollback_reason':value['reason']})
    atomic_write(path,json.dumps(saved))


def snapshot(cfg):
    p=cfg.state_dir/'routing-rollback.json'
    return [v for v in (json.loads(p.read_text('utf-8')).values() if p.exists() else []) if v.get('until',0)>time.time()]
