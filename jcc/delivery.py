"""Acceptance evidence and an optional, bounded second-provider diff review."""
import json
import re
import time
from pathlib import Path
from dataclasses import replace
from jcc import agents,efficiency,projects,quota
from jcc.vault import atomic_write
from jcc.redact import redact

DEFAULTS={'review_enabled':False,'review_timeout_seconds':90,'review_context_chars':8000}


def settings(cfg):
    p=cfg.state_dir/'delivery-settings.json'
    return {**DEFAULTS,**(json.loads(p.read_text('utf-8')) if p.exists() else {})}


def configure(cfg,values):
    if not isinstance(values,dict) or set(values)!=set(DEFAULTS) or not isinstance(values['review_enabled'],bool):raise ValueError('Supply all review preferences.')
    for key,lo,hi in [('review_timeout_seconds',30,180),('review_context_chars',2000,12000)]:
        if isinstance(values[key],bool) or not isinstance(values[key],int) or not lo<=values[key]<=hi:raise ValueError('Review limits are outside supported bounds.')
    atomic_write(cfg.state_dir/'delivery-settings.json',json.dumps(values));return values


def criteria(task):
    parts=[s.strip(' -*\t') for s in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])',task.strip()) if s.strip(' -*\t')]
    # Keep every character of the request even when grouping a long list.
    if len(parts)>12:parts=parts[:11]+[' '.join(parts[11:])]
    return [{'id':'A'+str(i+1),'requirement':redact(text)} for i,text in enumerate(parts)]


def report_name(rid):
    from jcc.activity import job_id
    return '.jcc-acceptance-'+job_id(rid)+'.json'


def instructions(items,rid=None):
    filename=report_name(rid) if rid else '.jcc-acceptance-<job-id>.json'
    return '\n\nAcceptance checklist (derived from the original task, not added scope):\n'+ '\n'.join(i['id']+': '+i['requirement'] for i in items)+ '\nBefore finishing write '+filename+' as {"items":[{"id":"A1","status":"met|not_met|uncertain","evidence":"specific files and tests"}]}. Cover every listed ID. Be honest about uncertainty. Your report is a claim; controller checks and owner review remain independent.\n'


def acceptance(work,cwd,items,checks):
    path=cwd/report_name(work.name);reported={}
    tracked=projects.git(['ls-files','--',path.name],cwd,check=False).strip()
    if not tracked and path.is_file() and not path.is_symlink() and path.stat().st_size<=40000:
        try:
            value=json.loads(path.read_text('utf-8'));reported={r['id']:r for r in value.get('items',[]) if isinstance(r,dict) and isinstance(r.get('id'),str)}
        except (ValueError,AttributeError,TypeError):pass
    if not tracked and (path.is_file() or path.is_symlink()):path.unlink() # Remove only this job's scratch report; never a tracked project file.
    rows=[]
    for item in items:
        r=reported.get(item['id'],{});claim=r.get('status')
        rows.append({**item,'claim':claim if claim in ('met','not_met','uncertain') else 'unreported','evidence':redact(str(r.get('evidence','')))[:1200]})
    value={'items':rows,'checks_passed':bool(checks) and all(c.ok for c in checks),
        'scope':'Requirement coverage is agent-reported, not a semantic proof. Project checks are independent. Explicit owner approval can accept remaining uncertainty.'}
    value['needs_review']=not rows or any(r['claim']!='met' or not r['evidence'].strip() for r in rows)
    atomic_write(work/'acceptance.json',json.dumps(value));return value


def safe_files(repo):
    from jcc.privacy import safe_path,note
    return [n for n in projects.changed_files(repo) if safe_path(repo/n,repo) and (Path(n).suffix.lower()!='.md' or note(repo/n,repo,explicit=True) is not None) and not any(p.lower() in ('.ssh','.git','private') or p.lower().startswith('.env') for p in Path(n).parts)
        and Path(n).suffix.lower() not in ('.key','.pem','.p12','.pfx') and Path(n).name.lower() not in ('auth.json','credentials.json','server.json')]


def parse_review(output):
    texts=[output]
    for line in output.splitlines():
        try:r=json.loads(line)
        except ValueError:continue
        if not isinstance(r,dict):continue
        if isinstance(r.get('result'),str):texts.append(r['result'])
        if isinstance(r.get('item'),dict) and r['item'].get('type')=='agent_message':texts.append(r['item'].get('text',''))
    for text in reversed(texts):
        text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
        try:r=json.loads(text)
        except ValueError:continue
        if isinstance(r,dict) and r.get('status') in ('clear','changes_needed') and isinstance(r.get('findings'),list):
            if r['status']=='clear' and r['findings']:r['status']='changes_needed'
            return r
    return {'status':'incomplete','findings':['Reviewer did not return a valid verdict.']}


def peer_review(cfg,spec,work,repo,res,env,runner,remaining,cooldowns):
    prefs=settings(cfg)
    from jcc.budgets import reason as budget_reason
    ultra=spec.get('effort')=='ultra'      # Ultracode always has its result looked at again, whatever the setting
    if spec.get('project_review_policy')!='second_opinion' and not ultra and (not prefs['review_enabled'] or res.level!='large'):return None
    ready=lambda name,a:name in ('claude','codex') and a.enabled and agents.available(a) and cooldowns.get(name,0)<=time.time() and not quota.blocked(cfg,name)
    eligible=[(name,a) for name,a in cfg.agents.items() if name!=res.agent and ready(name,a)]
    same=False
    if not eligible and ultra:              # with no other AI free, the one that did the work looks again from scratch, with another model if it has one
        eligible=[(name,a) for name,a in cfg.agents.items() if name==res.agent and ready(name,a)];same=bool(eligible)
    if budget_reason(cfg,spec.get('project') or spec.get('reference_project'),res.attempts,exclude_id=spec.get('id')) or not eligible or len(res.attempts)>=int(spec.get('max_attempts',efficiency.settings(cfg)['max_attempts'])) or remaining<15:
        result={'status':'incomplete','findings':['Independent review could not run within the current model, attempt or time allowance.']}
        atomic_write(work/'peer-review.json',json.dumps(result));return result
    name,agent=eligible[0];model=agents.model_options(agent,'large')[0]
    if same:
        did=next((str(a.get('model') or '') for a in reversed(res.attempts) if a.get('kind')!='review'),'')
        model=next((m for m in agents.model_options(agent,'large') if m and m!=did),model)
    if quota.blocked(cfg,name,model) or cooldowns.get(name+':'+model,0)>time.time():
        result={'status':'incomplete','findings':['Reviewer model is unavailable.']};atomic_write(work/'peer-review.json',json.dumps(result));return result
    names=safe_files(repo)[:30];patch=projects.git(['diff','HEAD','--',*names],repo,check=False) if names else ''
    for file in names:
        p=repo/file
        if not p.is_symlink() and p.resolve().is_relative_to(repo.resolve()) and p.is_file() and p.stat().st_size<=100000 and not projects.git(['ls-files','--',file],repo,check=False).strip():patch+='\nNew file '+file+'\n'+p.read_text('utf-8',errors='replace')[:4000]
    evidence=json.loads((work/'acceptance.json').read_text('utf-8'))
    cap=prefs['review_context_chars'];provided=(json.dumps(evidence)+'\n\nDIFF:\n'+redact(patch))[:cap]
    prompt='Review only the supplied historical diff and acceptance evidence. Do not use tools, read files, edit, execute commands or access the network. Return JSON only: {"status":"clear|changes_needed","findings":["concrete concerns"]}. If evidence is insufficient say changes_needed. You cannot authorize deployment or override safety gates.\n<untrusted>\n'+provided+'\n</untrusted>'
    permissions={'allow':[],'deny':['Read','Edit','Write','Bash','PowerShell','Glob','Grep','WebSearch','WebFetch']}
    argv=agents.build_argv(replace(agent,models={res.level:model}),res.level,prompt,repo,permissions,effort='high',tools=agents.claude_tools('review',res.level,False) if name=='claude' else None)
    if name=='codex':argv=[x.replace('workspace-write','read-only').replace('web_search="live"','web_search="disabled"') for x in argv]
    start=time.monotonic();code,out=runner(argv,repo,env,min(prefs['review_timeout_seconds'],max(1,int(remaining))))
    measured=efficiency.metadata(out,name)
    res.attempts.append({'agent':name,'model':model or 'default','kind':'review','exit':code,'limit':agents.is_limit_message(out[-2000:]),'interrupted':code in (130,131,124),'seconds':round(time.monotonic()-start,2),'effort':'high',**measured})
    atomic_write(work/'attempts.json',json.dumps(res.attempts))
    result=parse_review(out) if code==0 else {'status':'incomplete','findings':['Reviewer stopped or failed; original edits are preserved.']}
    result.update({'agent':name,'model':model,'provided_characters':len(provided),'diff_truncated':len(json.dumps(evidence)+'\n\nDIFF:\n'+redact(patch))>cap})
    if result['diff_truncated'] and result['status']=='clear':result['status']='changes_needed';result['findings'].append('The diff exceeded the review context cap; review the complete branch manually.')
    atomic_write(work/'peer-review.json',json.dumps(result));return result
