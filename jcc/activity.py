"""Durable, bounded activity and local completion alerts."""
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path
from jcc.vault import atomic_write, parse_frontmatter
from jcc.redact import redact


def job_id(value):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}', value): raise ValueError('Invalid job.')
    return value


def emit(cfg, rid, stage, message, **fields):
    work = cfg.jobs_root / job_id(rid); work.mkdir(parents=True, exist_ok=True)
    event = {'at': time.time(), 'stage': stage, 'message': redact(message)[:500],
             **{k: str(v)[:150] for k, v in fields.items() if k in ('agent', 'model')}}
    with (work / 'activity.jsonl').open('a', encoding='utf-8') as out:
        out.write(json.dumps(event) + '\n')


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


def alert(cfg, rid, status):
    if status not in ('done', 'failed', 'needs_approval','paused'): return
    path = cfg.jobs_root / job_id(rid) / 'alert.json'
    if path.exists() and json.loads(path.read_text('utf-8')).get('status') == status: return
    value = {'id': rid, 'at': time.time(), 'status': status, 'message': 'Job finished.' if status == 'done' else 'Job needs your review.' if status == 'needs_approval' else 'Job paused; work is preserved.' if status=='paused' else 'Job encountered a failure.'}
    atomic_write(path, json.dumps(value))
    from jcc.learning import settings
    if os.name != 'nt' or not settings(cfg)['desktop_alerts'] or os.environ.get('JCC_NO_CREDMAN'): return
    heartbeat=cfg.state_dir/'ui-active'
    if heartbeat.exists() and time.time()-heartbeat.stat().st_mtime<12: return
    # Fixed strings only: task text and secrets never enter a shell or notification.
    script = "Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; $n.BalloonTipTitle='JARVIS'; $n.BalloonTipText='A job finished or needs review. Open JARVIS for details.'; $n.ShowBalloonTip(5000); Start-Sleep -Seconds 6; $n.Dispose()"
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    subprocess.Popen(['powershell.exe', '-NoProfile', '-EncodedCommand', encoded], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def alerts(cfg):
    rows=[]
    for path in cfg.jobs_root.glob('*/alert.json'):
        try: rows.append(json.loads(path.read_text('utf-8')))
        except (OSError, ValueError): pass
    rows=[row for row in rows if isinstance(row,dict) and isinstance(row.get('at'),(int,float))]
    return sorted(rows, key=lambda x:x['at'], reverse=True)[:20]
