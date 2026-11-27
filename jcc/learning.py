"""Conservative routing learned from real checked work and explicit owner feedback."""
import json
import math
import re
import time
from collections import defaultdict
from statistics import median
from jcc.vault import atomic_write, read_json
from jcc.lock import InstanceLock

DEFAULTS = {"adaptive_routing": True, "review_before_merge": False, "desktop_alerts": True,
            "done_sound": True,             # (the sound when a task finishes: jcc/static/nova-audio.js, jcc/notices.py)
            "notice_titles": False}         # (the chat's name in the Windows notification: off unless asked for, jcc/notices.py)


def settings(cfg):
    p = cfg.state_dir / 'assistant-settings.json'
    return {**DEFAULTS, **read_json(p, {})}


def configure(cfg, values):
    """Change some of these preferences (on/off each); the others stay as they are."""
    if not isinstance(values, dict) or not values or not set(values) <= set(DEFAULTS) or any(not isinstance(v, bool) for v in values.values()):
        raise ValueError('Supply assistant preferences as on/off values.')
    merged = {**settings(cfg), **values}
    atomic_write(cfg.state_dir / 'assistant-settings.json', json.dumps(merged))
    return merged


def family(task, kind='job'):
    t = task.lower()
    if kind == 'chat': return 'discussion'
    if kind == 'rewrite': return 'prompt refinement'
    if re.search(r'\b(security|vulnerab\w*|risk engine|ledger|concurren\w*|race condition)\b', t): return 'critical systems'
    if re.search(r'\b(css|html|gui|ui|layout|frontend|styling|responsive)\b', t): return 'interface'
    if re.search(r'\b(bug|fix|regression|exception|traceback)\b', t): return 'debugging'
    if re.search(r'\b(readme|docstring|documentation|explain|comment|wording)\b', t): return 'documentation'
    if re.search(r'\b(test|tests|pytest|unittest)\b', t): return 'tested implementation'
    if kind == 'research': return 'research'
    return 'implementation'


def feedback(cfg):
    p = cfg.state_dir / 'job-feedback.json'
    return read_json(p, {})


def rate(cfg, rid, rating):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}', rid) or rating not in ('helpful', 'needs_work'):
        raise ValueError('Invalid job feedback.')
    p = cfg.jobs_root / rid / 'metrics.json'
    if not p.is_file(): raise ValueError('This job has no measured result to rate.')
    lock = InstanceLock(cfg.state_dir / 'feedback.lock')
    if not lock.acquire(): raise ValueError('Feedback is being saved; try again.')
    try:
        values = feedback(cfg); values[rid] = rating
        atomic_write(cfg.state_dir / 'job-feedback.json', json.dumps(values))
    finally: lock.release()
    return refresh(cfg)


def refresh(cfg):
    votes = feedback(cfg); buckets = defaultdict(list)
    for path in sorted(cfg.jobs_root.glob('*/metrics.json'), reverse=True)[:500]:
        try: row = json.loads(path.read_text('utf-8'))
        except (ValueError, OSError): continue
        if not row.get('task') or not row.get('level'): continue
        if row.get('updated_at',0) < time.time()-90*86400: continue
        task_family = row.get('family') or family(row['task'], row.get('kind', 'job'))
        last_impl=max((i for i,a in enumerate(row.get('runs',[])) if a.get('kind')!='review'),default=-1)
        for i, attempt in enumerate(row.get('runs', [])):
            if attempt.get('kind')=='review':continue
            if attempt.get('limit') or attempt.get('interrupted') or attempt.get('failure_class') == 'environment' or attempt.get('exit') != 0: continue
            last = i == last_impl
            checked = attempt.get('verified') is True or (last and row.get('checks_passed') is True)
            failed_check = attempt.get('checks_failed') is True or attempt.get('acceptance_failed') is True
            vote = votes.get(row['id']) if last else None
            if not checked and not failed_check and vote is None: continue
            ok = checked and not failed_check
            if vote == 'needs_work': ok = False
            elif vote == 'helpful' and not failed_check: ok = True
            key = (task_family, row['level'], attempt['agent'], attempt['model'])
            tokens = attempt.get('input_tokens')
            cached = attempt.get('cached_tokens')
            cost = max(0, tokens - cached) if tokens is not None and cached is not None else None
            buckets[key].append({'id': row['id'], 'ok': ok, 'checked': checked,
                'rated':vote == 'helpful', 'seconds': attempt.get('seconds', 0), 'uncached': cost,'effort':attempt.get('effort','auto'),'at':row.get('updated_at',0)})
    stats = []
    for (f, level, provider, model), raw_rows in buckets.items():
        rows=list({r['id']:r for r in raw_rows}.values())
        latest=max(r['at'] for r in rows);age=max(0,(time.time()-latest)/86400)
        # Independent tasks, not repeated attempts on one job, establish confidence.
        n = len({r['id'] for r in rows}); successes = len({r['id'] for r in rows if r['ok']})
        checked = len({r['id'] for r in rows if r['ok'] and r['checked']})
        rated = len({r['id'] for r in rows if r['ok'] and r['rated']})
        p = sum(r['ok'] for r in rows) / len(rows); z = 1.28
        lower = (p + z*z/(2*len(rows)) - z*math.sqrt(p*(1-p)/len(rows)+z*z/(4*len(rows)**2)))/(1+z*z/len(rows))
        seconds = median(r['seconds'] for r in rows)
        costs = [r['uncached'] for r in rows if r['uncached'] is not None]
        cost = median(costs) if costs else None
        score = lower - .03*min(seconds/300, 1) - (.03*min(cost/50000, 1) if cost is not None else 0)
        stats.append({'family': f, 'level': level, 'provider': provider, 'model': model, 'tasks': n,
            'successes': successes, 'checked_successes': checked, 'rated_successes':rated, 'success_rate': round(p, 3),
            'median_seconds': seconds, 'median_uncached_tokens': cost, 'score': round(score-.1*min(age/30,1), 4), 'latest_at':latest,'evidence_age_days':round(age,1),
            'eligible': age<=30 and n >= 5 and successes >= 3 and p >= (.7 if f == 'discussion' else .8) and (checked >= 3 or rated >= 3)})
    effort_stats=[]
    for (f,level,provider,model),rows in buckets.items():
        for effort in {r['effort'] for r in rows}:
            chosen=list({r['id']:r for r in rows if r['effort']==effort}.values());latest=max(r['at'] for r in chosen);age=max(0,(time.time()-latest)/86400);n=len({r['id'] for r in chosen})
            rate=sum(r['ok'] for r in chosen)/len(chosen)
            quality=len({r['id'] for r in chosen if r['ok'] and (r['checked'] or r['rated'])})
            costs=[r['uncached'] for r in chosen if r['uncached'] is not None]
            seconds=median(r['seconds'] or 0 for r in chosen)
            effort_stats.append({'family':f,'level':level,'provider':provider,'model':model,'effort':effort,
                'tasks':n,'success_rate':round(rate,3),'median_seconds':seconds,'median_uncached_tokens':median(costs) if costs else None,
                'eligible':age<=30 and n>=5 and quality>=3 and rate>=.8,'latest_at':latest,'evidence_age_days':round(age,1),
                'score':rate-.03*min(seconds/300,1)-(.03*min(median(costs)/50000,1) if costs else 0)})
    from jcc.routing_guard import apply
    apply(cfg,buckets,stats,effort_stats)
    result = {'at': time.time(), 'stats': sorted(stats, key=lambda x: x['score'], reverse=True),'effort_stats':effort_stats,
              'minimum_tasks': 5, 'source': 'Real checked jobs and owner ratings; no paid exploration.'}
    changes=cfg.state_dir/'routing-experiments.json'
    prior=json.loads(changes.read_text('utf-8')) if changes.exists() else []
    proposal=[(r['family'],r['level'],r['provider'],r['model']) for r in result['stats'] if r['eligible']]
    if not prior or prior[-1].get('eligible')!=[list(r) for r in proposal]:
        prior.append({'at':time.time(),'eligible':proposal,'scope':'Observed evidence changes, not paid exploration or causal A/B results.'})
        atomic_write(changes,json.dumps(prior[-100:]))
    atomic_write(cfg.state_dir / 'routing-learning.json', json.dumps(result))
    return result


def snapshot(cfg):
    p = cfg.state_dir / 'routing-learning.json'
    return {'settings': settings(cfg), 'evidence': read_json(p, {}) or {'stats': [], 'minimum_tasks': 5}, 'feedback': feedback(cfg)}


def rank(cfg, spec, candidates):
    f = family(spec['task'], spec.get('kind', 'job')); level = spec['level']
    if spec.get('manual_model', 'auto') != 'auto' or spec.get('prefer') not in (None, 'auto', ''):
        return candidates, 'Manual model/provider preference takes priority.'
    if cfg.raw.get('routing_choices', {}).get(level, {}).get('model', 'auto') != 'auto':
        return candidates, 'Your task-size model preference takes priority.'
    if not settings(cfg)['adaptive_routing']:
        return candidates, 'Adaptive routing is off; using the configured route.'
    if level == 'large' or f == 'critical systems':
        return candidates, 'Complex or critical work retains the configured strong route.'
    state = snapshot(cfg)['evidence']
    eligible = {(r['provider'], r['model']): r for r in state.get('stats', [])
                if r['family'] == f and r['level'] == level and r['eligible'] and (not r.get('latest_at') or time.time()-r['latest_at']<=30*86400)}
    # A model tried manually can earn a place in Auto once it has evidence.
    # Only current catalog entries on already eligible providers may enter.
    from jcc.models import catalog
    providers={c[0] for c in candidates}
    known={(m['provider'],m['model']) for m in catalog(cfg)}
    candidates=candidates+[c for c in eligible if c not in candidates and c in known and c[0] in providers]
    scored = [c for c in candidates if c in eligible]
    if not scored: return candidates, f'{f}: fewer than five qualifying tasks per candidate; using the configured route.'
    winner = max(scored, key=lambda c: eligible[c]['score']); row = eligible[winner]
    baseline = eligible.get(candidates[0])
    if baseline and winner != candidates[0] and row['score'] < baseline['score'] + .05:
        return candidates, 'The learned difference is too small to change the established route.'
    return [winner] + [c for c in candidates if c != winner], f"Learned {f} route: {winner[0]}/{winner[1]}, {row['successes']}/{row['tasks']} successful tasks. Quota and permission checks still apply."


def effort_for(cfg,spec,provider,model,attempts,supported):
    manual=spec.get('effort','auto')
    if manual=='ultra':     # Ultracode: as hard as this model can think, whatever its highest level is called
        hardest=[e for e in ('low','medium','high','xhigh','max') if e in supported]
        return (hardest[-1] if hardest else 'auto'),'Ultracode: thinking as hard as this model can.'
    if manual!='auto':return manual,'Your effort preference takes priority.'
    if not supported:return 'auto','This model has no configurable effort.'
    order=[e for e in ('low','medium','high','xhigh','max','ultra') if e in supported]
    effort={'small':'low','medium':'medium','large':'high'}[spec['level']]
    if effort not in order:effort=order[0] if order else 'auto'
    rows=[]
    if settings(cfg)['adaptive_routing'] and spec['level']!='large' and family(spec['task'],spec.get('kind','job'))!='critical systems':
        rows=[r for r in snapshot(cfg)['evidence'].get('effort_stats',[]) if r['eligible'] and (not r.get('latest_at') or time.time()-r['latest_at']<=30*86400) and r['family']==family(spec['task'],spec.get('kind','job')) and r['level']==spec['level'] and r['provider']==provider and r['model']==model and r['effort'] in order]
        if rows:effort=max(rows,key=lambda r:r['score'])['effort']
    # Explicit effort stays fixed; automatic effort gets one bounded escalation
    # after a check failure. The task's overall attempt/time budgets still apply.
    failed=next((a for a in reversed(attempts) if a.get('checks_failed') and a.get('failure_class')!='environment'),None)
    if failed and order:
        previous=failed.get('effort',effort)
        if previous in order:effort=order[min(order.index(previous)+1,len(order)-1)]
        return effort,'Independent checks failed; automatically increasing effort within supported levels.'
    return effort,'Evidence-based effort.' if rows else 'Automatic effort by task size.'
