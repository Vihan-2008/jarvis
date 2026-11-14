"""One bounded context composition shared by preview and execution."""
import re
from jcc import workspace, efficiency,agents


def budget(cfg,task,supplied='',records=(),project=None,expand=False):
    hard=efficiency.settings(cfg)['context_chars']
    if expand:return hard
    base={'small':2200,'medium':4200,'large':hard}[agents.classify_level(task)]
    explicit={n.strip().casefold().removesuffix('.md') for n in re.findall(r'\[\[([^\]|#]+)',task)}
    required=max((r.get('end',r['offset']) for r in records if r['name'].casefold() in explicit or r['name'].rsplit('/',1)[-1].casefold() in explicit or r['name']==f'Projects/{project}/Memory' or r['reason']=='Owner-selected decision.'),default=0)
    # Attachments/history and required project/explicit notes take precedence,
    # subject to the owner's overall hard context limit.
    return min(hard,max(base,len(supplied.lstrip())+2+required))


def compose(cfg, project, task, supplied='', manifest=None,expand=False,details=None):
    records=[]
    memory=workspace.memory(cfg,project,task,source_manifest=records)
    limit=budget(cfg,task,supplied,records,project,expand)
    if details is not None:details['budget']=limit
    text=(supplied+'\n\n'+memory).strip()[:limit]
    if manifest is not None:
        start=len((supplied+'\n\n').lstrip())
        manifest.extend({k:r[k] for k in ('name','reason')} for r in records if start+r['offset']<len(text))
    return text


def inspect(cfg, project, task, supplied=''):
    sources=[]
    details={};text=compose(cfg,project,task,supplied,sources,details=details)
    if '<chat-history>' in text: sources.append({'name':'Recent conversation','reason':'Up to four earlier turns, bounded to 2,400 characters.'})
    if supplied.split('<chat-history>')[0].strip(): sources.append({'name':'Selected attachments / shared page','reason':'Explicitly attached to this draft; attachment text receives the context budget first.'})
    return {'text':text,'characters':len(text),'budget':details['budget'],'hard_budget':efficiency.settings(cfg)['context_chars'],
        'estimated_tokens':(len(text)+3)//4,'sources':sources,
        'scope':'Draft context only. Token estimate uses characters / 4. Provider instructions, tool descriptions, your draft and any reused provider session add usage. Notes may change before Send.'}
