"""Unified local health, evidence and capability boundaries. No external probes."""
import json
import time
from collections import defaultdict
from statistics import median
from jcc import activity,budgets,diagnostics,evaluations,governor,insights,restorepoints,task_queue,release_health
from jcc.privacy import safe_path
from jcc.vault import atomic_write


def outcomes(cfg):
    groups=defaultdict(list)
    for path in sorted(cfg.jobs_root.glob('*/metrics.json'),reverse=True)[:1000]:
        if not safe_path(path,cfg.jobs_root):continue
        try:row=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):continue
        groups[row.get('project') or 'unattributed'].append(row)
    result=[]
    for project,rows in groups.items():
        checked=[r for r in rows if r.get('status')=='done' and r.get('checks_passed') is True]
        first=[r for r in checked if r.get('retries')==0]
        measured=[r for r in rows if r.get('runs') and all(a.get('input_tokens') is not None and a.get('output_tokens') is not None for a in r['runs'])]
        result.append({'project':project,'tasks':len(rows),'checked_completed':len(checked),'first_pass':len(first),'completion_rate':round(len(checked)/len(rows),3),
            'median_seconds':median(r.get('seconds',0) for r in checked) if checked else None,'fully_measured_tasks':len(measured),'repairs':sum(r.get('retries',0) for r in rows),'scope':'Up to 1,000 recorded jobs; discussions without checks are not classified as coding successes.'})
    return result


def baseline(cfg):
    result={'at':time.time(),'outcomes':outcomes(cfg),'comparisons':insights.dashboard(cfg),'scope':'Observed pre-update outcomes; no synthetic work or claimed causal savings.'}
    atomic_write(cfg.state_dir/'improvement-baseline.json',json.dumps(result));return result


def health(cfg):
    connections=diagnostics.snapshot(cfg);attention=[]
    for name,row in connections.items():
        status=str(row.get('status','unknown'))
        if row.get('error') or any(t in status.lower() for t in ('error','stale','not connected')):attention.append({'kind':'connection','title':name,'detail':row.get('error') or status,'action':'Open Memory & sync settings.'})
    evaluation=evaluations.status(cfg)
    if evaluation['status']=='failed':attention.append({'kind':'evaluation','title':'Update checks failed','detail':'Review failed fixed cases before relying on the affected behavior.','action':'Open App settings → Update reliability checks.'})
    queue=task_queue.snapshot(cfg)
    for task in queue['tasks']:
        if task['status'] in ('failed','paused','needs_approval'):attention.append({'kind':'task','title':task['task'][:120],'detail':task['reason'] or task['status'],'id':task['id'],'action':'Inspect Activity; work remains preserved.'})
    quotas={}
    for name in ('claude','codex'):
        path=cfg.state_dir/('quota-'+name+'.json')
        try:row=json.loads(path.read_text('utf-8')) if path.exists() else {}
        except (ValueError,OSError):row={}
        quotas[name]={'state':'unknown' if not row else 'stale' if time.time()-row.get('at',0)>600 else 'recent','at':row.get('at'),'scope':'Provider allowance reading; not an exact token balance.'}
    return {'at':time.time(),'attention':attention[:40],'connections':connections,'quota_freshness':quotas,'tasks':queue,
        'resources':{'settings':governor.settings(cfg),'power':governor.power(),'background_deferred':governor.reason(cfg),'cloud_deferred':governor.reason(cfg,True)},
        'budgets':budgets.snapshot(cfg),'outcomes':outcomes(cfg),'evaluations':evaluation,'restore_points':restorepoints.listing(cfg),
        'release':release_health.status(cfg),'screen_access':{'enabled':False,'scope':'This update does not activate screen, microphone, browser or desktop control. User-operated browser links and terminal remain explicit actions.'},
        'capabilities':[
            {'name':'Coding agents','state':'configured subscription CLIs','detail':'Only installed model catalog entries; saved sessions can expire.'},
            {'name':'Offline work','state':'available locally','detail':'Search, notes, drafts, chat organization, planning and handoffs remain local. Cloud models need a connection.'},
            {'name':'Account history','state':'partial by source','detail':'Loaded browser conversations and local coding logs can sync; complete closed/mobile/native-app history needs exports or supported provider access.'},
            {'name':'Web/browser tools','state':'explicitly shared pages','detail':'Opening links and attaching selected page text is supported. General autonomous browser/desktop control stays off.'},
            {'name':'Local AI models','state':'not configured','detail':'Optional provider integration requires a compatible installed runtime and model. No model download, paid API or replacement provider was installed.'}],
        'scope':'Local status, not proof of external service availability. No account sign-in or network probe occurs when opening this panel.'}


def timeline(cfg,rid):
    events=activity.events(cfg,rid);note=next((r for r in activity.recent(cfg) if r['id']==rid),{})
    work=cfg.jobs_root/activity.job_id(rid)
    def read(name):
        path=work/(name+'.json')
        return json.loads(path.read_text('utf-8')) if path.exists() and not path.is_symlink() and path.stat().st_size<150000 else None
    return {'id':rid,'status':note.get('status'),'events':events,'milestones':read('milestones'),'baseline':read('baseline'),'validation':read('validation'),'latest':events[-1] if events else None,
        'remaining':'Review retained changes.' if note.get('status')=='needs_approval' else 'No active work.' if note.get('status') in ('done','cancelled') else 'Inspect the latest stage and original acceptance checklist; completion time is not guessed.'}
