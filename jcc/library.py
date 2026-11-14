"""Owner-controlled organization, full-message search and independent chat branches."""
import json
import re
import time
from jcc.chats import Chats
from jcc.lock import InstanceLock
from jcc.redact import redact
from jcc.vault import atomic_write


def preferences(cfg):
    path=cfg.state_dir/'library.json'
    return {'chats':{},'views':[],**(json.loads(path.read_text('utf-8')) if path.exists() else {})}


def query(cfg,filters=None):
    filters=filters or {}
    if not isinstance(filters,dict) or set(filters)-{'q','project','tag','folder','pinned','archived','source'}:raise ValueError('Invalid conversation filters.')
    text=str(filters.get('q','')).strip().lower()
    if len(text)>180:raise ValueError('Search is limited to 180 characters.')
    prefs=preferences(cfg);rows=[];chats=Chats(cfg)
    for row in chats.list()[:1500]:
        meta=prefs['chats'].get(row['id'],{});row={**row,**meta}
        if any(filters.get(k) and row.get(k)!=filters[k] for k in ('project','folder','source')):continue
        if filters.get('tag') and filters['tag'] not in row.get('tags',[]):continue
        if filters.get('pinned') is True and not row.get('pinned'):continue
        if 'archived' in filters and bool(row.get('archived'))!=filters['archived']:continue
        if text:
            chat=chats.get(row['id']);match=next((m['content'] for m in chat.get('messages',[]) if text in str(m.get('content','')).lower()),'')
            if text not in row['title'].lower() and not match:continue
            at=max(0,match.lower().find(text)-80);row['snippet']=match[at:at+280]
        rows.append(row)
    rows.sort(key=lambda r:(bool(r.get('pinned')),r.get('updated') or 0),reverse=True)
    return {'chats':rows[:150],'total':len(rows),'views':prefs['views'],'scope':'Local saved conversations; archived and private source exclusions apply. Full account history still depends on exports or supported capture.'}


def organize(cfg,cid,value):
    Chats(cfg).get(cid)
    if not isinstance(value,dict) or set(value)!={'folder','tags','pinned'}:raise ValueError('Supply folder, tags and pin preference.')
    if not isinstance(value['folder'],str) or len(value['folder'])>60 or not isinstance(value['pinned'],bool):raise ValueError('Invalid folder or pin preference.')
    tags=value['tags']
    if not isinstance(tags,list) or len(tags)>12 or any(not isinstance(t,str) or not re.fullmatch(r'[\w -]{1,32}',t) for t in tags):raise ValueError('Choose up to twelve short tags.')
    lock=InstanceLock(cfg.state_dir/'library.lock')
    if not lock.acquire():raise ValueError('Library is being saved. Try again.')
    try:
        prefs=preferences(cfg);prefs['chats'][cid]={'folder':redact(value['folder'].strip()),'tags':list(dict.fromkeys(tags)),'pinned':value['pinned']};atomic_write(cfg.state_dir/'library.json',json.dumps(prefs))
    finally:lock.release()
    return prefs['chats'][cid]


def save_view(cfg,name,filters):
    name=str(name).strip()
    if not 1<=len(name)<=60:raise ValueError('Name this saved view in 1–60 characters.')
    query(cfg,filters)
    lock=InstanceLock(cfg.state_dir/'library.lock')
    if not lock.acquire():raise ValueError('Library is being saved. Try again.')
    try:
        prefs=preferences(cfg);views=[v for v in prefs['views'] if v['name']!=name]
        if len(views)>=20:raise ValueError('At most twenty saved views are supported.')
        prefs['views']=[*views,{'name':redact(name),'filters':filters}];atomic_write(cfg.state_dir/'library.json',json.dumps(prefs))
    finally:lock.release()
    return prefs['views']


def branch(cfg,cid,index,title=''):
    chats=Chats(cfg);original=chats.get(cid);messages=original['messages']
    if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(messages):raise ValueError('Choose an existing message to branch from.')
    selected=messages[:index+1]
    if len(selected)>300 or sum(len(m.get('content','')) for m in selected)>500000:raise ValueError('This branch is too large; start from a compact project handoff.')
    result=chats.create(title or original['title']+' · branch',original.get('project'))
    result['branched_from']={'chat':cid,'message_index':index,'at':time.time()}
    result['messages']=[{k:m[k] for k in ('role','content','at','image_ids') if k in m} for m in selected]
    chats.save(result)
    return result
