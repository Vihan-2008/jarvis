"""Reusable rewrite preferences; no automatic task execution."""
import difflib
import json
from jcc.vault import atomic_write

DEFAULTS={'style':'detailed','template':'','review_all':True}      # detailed: a full build brief for something to build


def settings(cfg):
    path=cfg.state_dir/'prompt-preferences.json'
    return {**DEFAULTS,**(json.loads(path.read_text('utf-8')) if path.exists() else {})}


def configure(cfg,value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULTS) or value['style'] not in ('detailed','concise','coding','research') or not isinstance(value['template'],str) or len(value['template'])>1500 or not isinstance(value['review_all'],bool):raise ValueError('Invalid prompt preferences.')
    atomic_write(cfg.state_dir/'prompt-preferences.json',json.dumps(value));return value


def comparison(original,prompt):
    return {'diff':'\n'.join(difflib.unified_diff(original.splitlines(),prompt.splitlines(),fromfile='Your draft',tofile='Suggested prompt',lineterm=''))[:8000],
        'scope':'A wording comparison, not proof of equivalent intent. Review assumptions and retained constraints before sending.'}
