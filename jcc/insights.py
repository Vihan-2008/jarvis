"""Compare like task families; keep unknown usage and quality explicit."""
import json
import time
from collections import defaultdict
from statistics import median
from jcc.learning import feedback,family


def dashboard(cfg):
    votes=feedback(cfg);groups=defaultdict(list);recent=[]
    now=time.time()
    for path in sorted(cfg.jobs_root.glob('*/metrics.json'),reverse=True)[:500]:
        try:row=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):continue
        if row.get('updated_at',0)<now-30*86400:continue
        runs=row.get('runs',[]);last=next((r for r in reversed(runs) if r.get('kind')!='review'),{})
        verified=row.get('status')=='done' and (row.get('checks_passed') or votes.get(row['id'])=='helpful') and votes.get(row['id'])!='needs_work'
        measured=len(runs)>0 and all(r.get('input_tokens') is not None and r.get('cached_tokens') is not None for r in runs)
        uncached=sum(max(0,r['input_tokens']-r['cached_tokens']) for r in runs) if measured else None
        entry={'id':row['id'],'task':row.get('task',''),'at':row.get('updated_at',0),'verified':bool(verified),
            'status':row.get('status'),'seconds':row.get('seconds',0),'uncached':uncached,'retries':row.get('retries',0),
            'family':row.get('family') or family(row.get('task',''),row.get('kind','job')),'level':row.get('level','unknown'),
            'model':str(last.get('agent','unknown'))+'/'+str(last.get('model','unknown')),'effort':last.get('effort','auto')}
        groups[(entry['family'],entry['level'],entry['model'],entry['effort'])].append(entry);recent.append(entry)
    summaries=[]
    for (f,level,model,effort),rows in groups.items():
        current=[r for r in rows if r['at']>=now-7*86400];previous=[r for r in rows if now-14*86400<=r['at']<now-7*86400]
        def period(values):
            checked=[r for r in values if r['verified']];counts=[r['uncached'] for r in checked if r['uncached'] is not None]
            return {'tasks':len(values),'verified':len(checked),'median_seconds':median(r['seconds'] for r in checked) if checked else None,
                'median_uncached':median(counts) if counts else None,'measured_verified':len(counts),'retries':sum(r['retries'] for r in values)}
        a,b=period(current),period(previous)
        delta=round((a['median_uncached']/b['median_uncached']-1)*100,1) if min(a['measured_verified'],b['measured_verified'])>=5 and b['median_uncached'] else None
        summaries.append({'family':f,'level':level,'model':model,'effort':effort,'current':a,'previous':b,'uncached_change_percent':delta})
    return {'at':now,'jobs':sorted(recent,key=lambda x:x['at'],reverse=True)[:30], 'groups':summaries[:40],
        'totals':{'tasks':len(recent),'verified':sum(r['verified'] for r in recent),'retries':sum(r['retries'] for r in recent),
            'fully_measured':sum(r['uncached'] is not None for r in recent)},
        'scope':'Up to 500 jobs from the last 30 days. Weekly comparisons match task family, size, model and effort. A change is descriptive, not proof that routing caused it. Unrated discussions are not treated as verified successes.'}
