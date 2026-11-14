"""Local execution preview: no provider calls, receipts, jobs or chat mutations."""
import re
import time
from jcc import agents,context_inspector,delivery,guard,learning,models,project_policy,quota,budgets
from jcc.jobs import detect_project
from jcc.usage import Usage
from jcc.router import apply_rules


def preview(cfg,text,project=None,mode='auto',manual_model='auto',effort='auto',agent='auto',supplied=''):
    if not text or len(text)>2000:raise ValueError('Write a draft of up to 2,000 characters.')
    if mode not in ('auto','code','chat'):raise ValueError('Choose Auto, Build or Ask mode.')
    if project not in (None,'','auto','none',*cfg.projects):raise ValueError('Project not found.')
    proj=cfg.projects.get(project) if project in cfg.projects else None if project=='none' else detect_project(cfg,text)
    selected=models.validate(cfg,manual_model,effort)
    if selected:agent=selected['provider']
    rule=apply_rules(text)
    if mode=='auto' and project in cfg.projects and not re.match(r'^(what|why|how|explain|describe|can you explain|tell me|summarize)\b',text,re.I):mode='code'
    elif mode=='chat':mode='assistant'
    elif mode=='auto' and not text.startswith('/') and (not rule or rule.tier==2):mode='assistant'
    private=guard.personal_reason(text)
    local=mode in ('code','assistant') and private not in (None,'trading bot data') or mode=='auto' and rule and rule.tier==1
    kind='job' if mode=='code' else 'chat' if mode=='assistant' else rule.handler if rule else 'undetermined'
    coding=kind=='job' and not local
    block=guard.tier3_block_reason(text,[str(p) for p in cfg.protected]) if not local else private
    if kind=='chat' and block!='keys/secrets' and not str(block).startswith('protected folder') and re.match(r'^(what|why|how|explain|describe|tell me|summarize)\b',text,re.I):block=None
    usage=Usage(cfg.state_dir,cfg.caps)
    try:cooldowns=usage.cooldowns();plan=agents.plan(cfg,text,cooldowns,prefer=agent if agent!='auto' else None)
    finally:usage.close()
    candidates=[(n,m) for n in plan.agents for m in agents.model_options(cfg.agents[n],plan.level) if cooldowns.get(n+':'+m,0)<=time.time()]
    if selected and selected['provider'] in plan.agents:
        requested=(selected['provider'],selected['model'])
        if cooldowns.get(':'.join(requested),0)<=time.time():candidates=[requested]+[c for c in candidates if c!=requested]
    if effort=='auto' and manual_model=='auto':effort=cfg.raw.get('routing_choices',{}).get(plan.level,{}).get('effort','auto')
    spec={'task':text,'kind':kind,'level':plan.level,'manual_model':manual_model,'effort':effort,'prefer':agent}
    candidates,reason=learning.rank(cfg,spec,candidates)
    candidates=[(n,m) for n,m in candidates if cooldowns.get(n+':'+m,0)<=time.time() and not quota.blocked(cfg,n,m)]
    first=None;chosen_effort='auto';effort_reason='No coding agent selected.'
    if not local:
        catalog=models.catalog(cfg)
        for candidate in candidates:
            supported=next((m['efforts'] for m in catalog if m['provider']==candidate[0] and m['model']==candidate[1]),['low','medium','high'])
            selected_effort,why=learning.effort_for(cfg,spec,*candidate,[],supported)
            if selected_effort not in ('auto',*supported):continue
            first=candidate;chosen_effort=selected_effort;effort_reason=why;break
    policy=project_policy.snapshot(cfg,proj.key) if proj else None
    return {'dry_run':True,'kind':'local' if local else kind,'project':proj.name if proj else 'General workspace','project_key':proj.key if proj else None,
        'milestones':milestones(text,plan.level,kind),'level':plan.level,'model':{'provider':first[0],'name':first[1] or 'provider default','effort':chosen_effort} if first else None,
        'routing_reason':reason,'effort_reason':effort_reason,'blocked_by':block or budgets.reason(cfg,proj.key if proj else None),'skipped':plan.skipped,'acceptance':delivery.criteria(text),
        'context':context_inspector.inspect(cfg,proj.key if proj else None,text,supplied),
        'required_checks':policy['required_checks'] if coding and policy else [],'project_preferences':policy,
        'actions':(['Edit only an isolated project branch','Run required checks','Merge only after all configured gates pass' if policy and policy['auto_merge'] else 'Retain changes for owner review'] if coding and proj else ['Write the answer in an isolated chat workspace'] if not local else ['Read local vault data; no coding agent']),
        'restrictions':['No deployment, trading actions, secrets, push or protected-file changes'],
        'scope':'Snapshot only; availability and files can change before Send. No agent was called and no job was created. Auto commands without a deterministic route remain undecided.'}


def milestones(task,level=None,kind='job'):
    if kind!='job':return [{'id':'M1','title':'Understand the request and relevant context','requirements':['A1'],'done_when':'Original intent and constraints are retained.'},{'id':'M2','title':'Prepare the requested answer','requirements':[],'done_when':'Sources, assumptions and remaining uncertainty are explicit; no project code changes.'}]
    level=level or agents.classify_level(task);items=delivery.criteria(task)
    steps=[{'id':'M1','title':'Inspect the relevant project and current behavior','requirements':[],'done_when':'Scope and existing checks are understood.'}]
    if level=='large':
        for start in range(0,len(items),3):steps.append({'id':'M'+str(len(steps)+1),'title':'Implement requirements '+', '.join(i['id'] for i in items[start:start+3]),'requirements':[i['id'] for i in items[start:start+3]],'done_when':'Evidence recorded for these original requirements.'})
    else:steps.append({'id':'M2','title':'Implement the requested change','requirements':[i['id'] for i in items],'done_when':'Requested behavior is implemented without unrelated scope.'})
    steps.append({'id':'M'+str(len(steps)+1),'title':'Validate and summarize','requirements':[],'done_when':'All required checks and acceptance gates pass; unresolved issues are explicit.'})
    return steps
