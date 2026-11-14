"""Persistent priorities and dependency gates shared by dispatch and UI."""
import json
import time
from jcc import activity
from jcc.lock import InstanceLock
from jcc.vault import Vault,atomic_write,parse_frontmatter


def preferences(cfg):
    p=cfg.state_dir/'task-queue.json'
    return json.loads(p.read_text('utf-8')) if p.exists() else {}


def notes(cfg):
    rows=[]
    for p in sorted((cfg.vault/'Jobs').glob('*.md'),reverse=True):
        try:activity.job_id(p.stem)
        except ValueError:continue
        fm,_=parse_frontmatter(p.read_text('utf-8'))
        if fm.get('private'):continue
        rows.append({**fm,'id':p.stem})
    return rows


def blocked(cfg,rid,rows=None,prefs=None):
    rows={r['id']:r for r in (rows if rows is not None else notes(cfg))}
    deps=(prefs if prefs is not None else preferences(cfg)).get(rid,{}).get('dependencies',[])
    pending=[d for d in deps if rows.get(d,{}).get('status')!='done']
    return 'Waiting for prerequisite tasks: '+', '.join(pending) if pending else ''


def ordered(cfg):
    prefs=preferences(cfg)
    return sorted(notes(cfg),key=lambda r:(-prefs.get(r['id'],{}).get('priority',0),prefs.get(r['id'],{}).get('deadline') or float('inf'),r['id']))


def update(cfg,rid,priority,dependencies,deadline=None):
    activity.job_id(rid)
    if isinstance(priority,bool) or not isinstance(priority,int) or priority not in (-1,0,1):raise ValueError('Choose low, normal or high priority.')
    if not isinstance(dependencies,list) or len(dependencies)>12 or any(not isinstance(d,str) for d in dependencies) or len(set(dependencies))!=len(dependencies):raise ValueError('Choose up to twelve distinct prerequisites.')
    if deadline is not None and (isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not 0<=deadline<time.time()+5*365*86400):raise ValueError('Choose a valid deadline within five years.')
    dispatch=InstanceLock(cfg.state_dir/'launch.lock')
    if not dispatch.acquire():raise ValueError('A task is being dispatched. Try again.')
    lock=InstanceLock(cfg.state_dir/'task-queue.lock')
    try:
        rows={r['id']:r for r in notes(cfg)}
        if rid not in rows or rows[rid].get('status') not in ('queued','paused','failed'):raise ValueError('Only waiting, paused or failed tasks can be rescheduled.')
        for dep in dependencies:
            activity.job_id(dep)
            if dep==rid or dep not in rows:raise ValueError('A prerequisite must be another existing task.')
        if not lock.acquire():raise ValueError('Queue is being updated; try again.')
        prefs=preferences(cfg);prefs[rid]={'priority':priority,'dependencies':dependencies,'deadline':(deadline or None) if deadline is not None else prefs.get(rid,{}).get('deadline')}
        visited=set()
        def walk(node,trail):
            if node in trail:raise ValueError('Prerequisites cannot form a cycle.')
            if node in visited:return
            for dep in prefs.get(node,{}).get('dependencies',[]):walk(dep,trail|{node})
            visited.add(node)
        walk(rid,set());atomic_write(cfg.state_dir/'task-queue.json',json.dumps(prefs))
    finally:
        lock.release();dispatch.release()
    return snapshot(cfg)


def snapshot(cfg):
    prefs=preferences(cfg);all_rows=ordered(cfg);out=[]
    active=[r for r in all_rows if r.get('status') not in ('done','cancelled')]
    finished=sorted((r for r in all_rows if r.get('status') in ('done','cancelled')),key=lambda r:r['id'],reverse=True)[:30]
    for r in active+finished:
        p=prefs.get(r['id'],{});reason=blocked(cfg,r['id'],all_rows,prefs)
        status=r.get('status','unknown')
        out.append({'id':r['id'],'task':str(r.get('task') or 'Untitled task')[:2000],'status':status,
            'display_status':'blocked' if reason and status=='queued' else status,'project':r.get('project_key'),
            'deadline':p.get('deadline'),'overdue':bool(p.get('deadline') and p['deadline']<time.time()),'priority':p.get('priority',0),'dependencies':p.get('dependencies',[]),
            'reason':reason or r.get('wait_reason') or r.get('skipped') or ('Waiting for an available worker or model.' if status=='queued' else r.get('recovery_reason',''))})
    return {'tasks':out[:150],'next':next((r['id'] for r in out if r['status']=='queued' and not blocked(cfg,r['id'],all_rows,prefs)),None)}
