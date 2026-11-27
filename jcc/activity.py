"""Durable, bounded activity and local completion alerts."""
import json
import os
import re
import time
from pathlib import Path
from jcc.vault import atomic_write, parse_frontmatter
from jcc.redact import redact
from jcc import notch

# How a job's stage shows on the NotchPixel island (jcc/notch.py). Any other stage is the job thinking: planning,
# gathering context, or waiting its turn for an agent (which is not waiting for its owner).
ISLAND = {'working': 'working', 'repair': 'working', 'checking': 'working', 'acceptance': 'working',
          'needs_approval': 'waiting', 'paused': 'waiting', 'done': 'done', 'merged': 'done', 'failed': 'error', 'cancelled': 'end'}


def job_id(value):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}', value): raise ValueError('Invalid job.')
    return value


def emit(cfg, rid, stage, message, **fields):
    work = cfg.jobs_root / job_id(rid); work.mkdir(parents=True, exist_ok=True)
    event = {'at': time.time(), 'stage': stage, 'message': redact(message)[:500],
             **{k: str(v)[:150] for k, v in fields.items() if k in ('agent', 'model')}}
    with (work / 'activity.jsonl').open('a', encoding='utf-8') as out:
        out.write(json.dumps(event) + '\n')
    notch.tell(cfg, rid, ISLAND.get(stage, 'thinking'), event['message'])


def events(cfg, rid):
    p = cfg.jobs_root / job_id(rid) / 'activity.jsonl'
    if not p.exists(): return []
    rows = []
    for line in p.read_text('utf-8').splitlines()[-80:]:
        try: rows.append(json.loads(line))
        except ValueError: pass
    return rows


def recent(cfg):
    rows = []
    for p in sorted((cfg.vault / 'Jobs').glob('*.md'), reverse=True)[:40]:
        if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}',p.stem): continue
        try: fm, _ = parse_frontmatter(p.read_text('utf-8'))
        except (OSError, ValueError): continue          # a note that cannot be read right now is left out, not fatal
        row={k: fm.get(k) for k in ('id', 'task', 'status', 'agent', 'model', 'project_key', 'routing_reason', 'merged','started_at')}
        row['id']=p.stem
        try: row['latest_event'] = (events(cfg,str(fm.get('id'))) or [None])[-1]
        except ValueError: row['latest_event'] = None
        rows.append(row)
    return rows


def _chat_of(cfg, rid):
    """The chat a job belongs to (for a click on its notification), or ''."""
    try: fm, _ = parse_frontmatter((cfg.vault / 'Jobs' / f'{job_id(rid)}.md').read_text('utf-8'))
    except (OSError, ValueError): return ''
    return str(fm.get('chat_id') or '')


def alert(cfg, rid, status):
    if status not in ('done', 'failed', 'needs_approval','paused'): return
    path = cfg.jobs_root / job_id(rid) / 'alert.json'
    if path.exists() and json.loads(path.read_text('utf-8')).get('status') == status: return
    value = {'id': rid, 'at': time.time(), 'status': status, 'message': 'Job finished.' if status == 'done' else 'Job needs your review.' if status == 'needs_approval' else 'Job paused; work is preserved.' if status=='paused' else 'Job encountered a failure.'}
    atomic_write(path, json.dumps(value))
    # The island already shows a status its job wrote last; this is for one reached another way (a recovered worker).
    if notch.enabled(cfg) and (events(cfg, rid) or [{}])[-1].get('stage') != status:
        notch.tell(cfg, rid, ISLAND[status], value['message'])
    # The Windows notification (fixed words; shown by the tray helper, or a PowerShell balloon without it): jcc/notices.py.
    from jcc import notices
    try: notices.finished(cfg, rid, status, chat=_chat_of(cfg, rid), background=True)
    except Exception: pass  # noqa: BLE001 - a notification must never break a job


def alerts(cfg):
    rows=[]
    for path in cfg.jobs_root.glob('*/alert.json'):
        try: rows.append(json.loads(path.read_text('utf-8')))
        except (OSError, ValueError): pass
    rows=[row for row in rows if isinstance(row,dict) and isinstance(row.get('at'),(int,float))]
    return sorted(rows, key=lambda x:x['at'], reverse=True)[:20]
