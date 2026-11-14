"""Incremental local full-text retrieval. No cloud or model call is required."""
import re
import sqlite3
from jcc.vault import parse_frontmatter
from jcc.redact import redact

STOP = set('the a an and or to of in on for with my this that is are can you please add fix make run tests test what how why'.split())


def eligible(path, root):
    rel = path.relative_to(root).as_posix()
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or any(p.startswith('.') or p.lower() == 'private' for p in path.relative_to(root).parts):
        return None
    if rel.startswith(('Conversations/Imported/', 'Conversations/Local/', 'Requests/', 'Jobs/')) or '/Jobs/' in rel:
        return None
    from jcc.privacy import note
    value=note(path,root)
    return value[1] if value and not value[0].get('superseded_by') else None


def search(cfg, query, project=None, limit=3):
    words = [w for w in dict.fromkeys(re.findall(r'[\w-]{3,}', query.lower())) if w not in STOP][:12]
    if not words:
        return []
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cfg.state_dir / 'memory-search.sqlite3', timeout=30)
    try:
        db.execute('create table if not exists files(path text primary key, signature text)')
        db.execute('create virtual table if not exists passages using fts5(path UNINDEXED, content)')
        known = dict(db.execute('select path, signature from files'))
        seen = set()
        for path in cfg.vault.rglob('*.md'):
            rel = path.relative_to(cfg.vault).as_posix()
            seen.add(rel)
            stamp = f'{path.stat().st_mtime_ns}:{path.stat().st_size}'
            if known.get(rel) == stamp:
                continue
            body = eligible(path, cfg.vault)
            db.execute('delete from passages where path=?', (rel,))
            db.execute('insert or replace into files values (?,?)', (rel, stamp))
            if body:
                # The archive is preserved on disk; this index contains bounded passages.
                for i in range(0, len(body), 1200):
                    db.execute('insert into passages(path,content) values (?,?)', (rel, redact(body[i:i+1400])))
        for rel in known.keys() - seen:
            db.execute('delete from passages where path=?', (rel,))
            db.execute('delete from files where path=?', (rel,))
        db.commit()
        expression = ' OR '.join('"' + w.replace('"', '') + '"' for w in words)
        where = ' and path like ?' if project else ''
        args = [expression, f'Projects/{project}/%'] if project else [expression]
        rows = db.execute('select path,content from passages where passages match ?' + where + ' order by rank limit 12', args)
        found, paths = [], set()
        for rel, content in rows:
            # Recheck privacy now, even when a cached file signature is unchanged.
            path = cfg.vault / rel
            if rel in paths or not path.is_file() or eligible(path, cfg.vault) is None:
                continue
            found.append((rel, content[:900]))
            paths.add(rel)
            if len(found) >= limit:
                break
        return found
    finally:
        db.close()
