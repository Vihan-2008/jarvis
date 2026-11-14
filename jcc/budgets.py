"""Local measured budget gates. Token caps are soft when a provider omits usage."""
import json
import time
from jcc.vault import atomic_write

DEFAULTS={'daily_seconds':0,'daily_tokens':0,'task_tokens':0,'reserve_percent':5,'projects':{}}


def settings(cfg):
    path=cfg.state_dir/'budgets.json'
    return {**DEFAULTS,**(json.loads(path.read_text('utf-8')) if path.exists() else {})}


def configure(cfg,value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULTS):raise ValueError('Supply all budget preferences.')
    for key,maximum in (('daily_seconds',86400),('daily_tokens',100000000),('task_tokens',10000000),('reserve_percent',50)):
        if isinstance(value[key],bool) or not isinstance(value[key],int) or not 0<=value[key]<=maximum:raise ValueError('Budget value is outside its allowed range.')
    if not isinstance(value['projects'],dict) or set(value['projects'])-set(cfg.projects):raise ValueError('Unknown project budget.')
    for prefs in value['projects'].values():
        if not isinstance(prefs,dict) or set(prefs)!={'daily_seconds','daily_tokens'} or any(isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=100000000 for v in prefs.values()):raise ValueError('Invalid project budget.')
    atomic_write(cfg.state_dir/'budgets.json',json.dumps(value));return value


def usage(cfg,project=None,exclude_id=None):
    today=time.localtime();start=time.mktime((today.tm_year,today.tm_mon,today.tm_mday,0,0,0,0,0,-1));seconds=0;tokens=0;unknown=0;jobs=0
    for path in cfg.jobs_root.glob('*/metrics.json'):
        if path.is_symlink() or not path.resolve().is_relative_to(cfg.jobs_root.resolve()):continue
        try:row=json.loads(path.read_text('utf-8'))
        except (ValueError,OSError):continue
        if row.get('id')==exclude_id:continue
        if row.get('updated_at',0)<start or project and row.get('project')!=project:continue
        jobs+=1;seconds+=max(0,row.get('seconds',0));runs=row.get('runs',[])
        # Never turn missing usage into an apparent zero-token task.
        for run in runs:
            if isinstance(run.get('input_tokens'),int) and isinstance(run.get('output_tokens'),int):tokens+=max(0,run['input_tokens'])+max(0,run['output_tokens'])
            else:unknown+=1
    return {'jobs':jobs,'seconds':round(seconds,2),'measured_tokens':tokens,'unmeasured_attempts':unknown}


def reason(cfg,project=None,attempts=(),exclude_id=None):
    prefs=settings(cfg);all_usage=usage(cfg,exclude_id=exclude_id)
    scopes=[('Daily',prefs,all_usage)]
    if project and project in prefs['projects']:scopes.append(('Project',prefs['projects'][project],usage(cfg,project,exclude_id)))
    current_tokens=sum(max(0,a.get('input_tokens') or 0)+max(0,a.get('output_tokens') or 0) for a in attempts)
    current_seconds=sum(max(0,a.get('seconds') or 0) for a in attempts)
    for label,limits,spent in scopes:
        for key,amount in (('daily_tokens',spent['measured_tokens']+current_tokens),):      # (there is no time budget: work runs until it is done)
            if limits.get(key) and amount>=limits[key]*(1-prefs['reserve_percent']/100):return label+' '+('time' if key.endswith('seconds') else 'measured token')+' budget reached; work is preserved.'
    if prefs['task_tokens'] and current_tokens>=prefs['task_tokens']:return 'Task measured token budget reached; work is preserved.'
    return None


def remaining_seconds(cfg,project=None,attempts=(),exclude_id=None):
    return None                     # there is no time budget any more: work runs until it is done
    prefs=settings(cfg);remaining=[];current=sum(max(0,a.get('seconds') or 0) for a in attempts)
    for key,limits in ((None,prefs),(project,prefs['projects'].get(project,{}))):
        if limits.get('daily_seconds'):
            spent=usage(cfg,key,exclude_id)['seconds'];remaining.append(max(0,int(limits['daily_seconds']*(1-prefs['reserve_percent']/100)-spent-current)))
    return min(remaining) if remaining else None


def snapshot(cfg):
    prefs=settings(cfg)
    return {'settings':prefs,'usage':usage(cfg),'projects':{k:usage(cfg,k) for k in prefs['projects']},'blocked_by':reason(cfg),'scope':'0 means no extra cap. Time is bounded per running attempt. Token caps use reported measurements and are checked between calls; parallel or unmeasured usage can exceed them. Subscription allowance remains a separate provider limit.'}
