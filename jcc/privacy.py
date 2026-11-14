"""One exclusion policy for retrieval, previews, indexing and exports."""
from pathlib import Path

SECRET_NAMES={'id_rsa','id_ed25519','server.json','credentials.json','auth.json','browser-sync-key'}


def safe_path(path,root):
    path,root=Path(path),Path(root)
    try:
        resolved=path.resolve();base=root.resolve()
        if path.is_symlink() or not resolved.is_relative_to(base):return False
        for parts in (path.relative_to(root).parts,resolved.relative_to(base).parts):
            if any(p.startswith('.') or p.lower() in ('private','credentials','secrets') for p in parts):return False
        return path.name.lower() not in SECRET_NAMES and path.suffix.lower() not in ('.pem','.key','.p12','.pfx')
    except (ValueError,OSError):return False


def truth(value):
    return value is True or isinstance(value,str) and value.lower() in ('true','yes','1')


def withheld(fm):
    """Whether a note's own header keeps it from being read for an assistant: marked private, or its use as context switched off.
    One rule for notes and for chats, for a list and for a single one asked for by its name."""
    return truth(fm.get('private')) or fm.get('ai_context') in ('exclude','off','none')


def note(path,root,*,cloud=False,explicit=False,limit=32000000,_seen=None,headers_only=False):
    from jcc.vault import parse_frontmatter
    if not safe_path(path,root) or not path.is_file() or path.stat().st_size>limit:return None
    try:
        with path.open('r',encoding='utf-8-sig') as stream:
            first=stream.readline();header=first
            if first.strip()=='---':
                for line in stream:
                    header+=line
                    if len(header)>min(limit,16000000):return None
                    if line.strip()=='---':break
                else:return None
                fm,_=parse_frontmatter(header+'\n')
                if withheld(fm) or not explicit and fm.get('ai_context')=='explicit-links-only' or cloud and fm.get('cloud_sync') is False:return None
                linked=fm.get('imported_note')
                if linked:
                    seen=set(_seen or ());identity=str(path.resolve())
                    if identity in seen or len(seen)>4:return None
                    seen.add(identity)
                    if note(Path(root)/str(linked),root,cloud=cloud,explicit=True,limit=limit,_seen=seen,headers_only=True) is None:return None
                return fm,'' if headers_only else stream.read()
            return {},'' if headers_only else first+stream.read()
    except (OSError,UnicodeError):return None


def chat_metadata(path,root):
    """Check every header, while avoiding JSON parsing of the large messages field."""
    from jcc.vault import parse_frontmatter
    if not safe_path(path,root):return None
    header=[];size=0
    try:
        with path.open('r',encoding='utf-8') as stream:
            if stream.readline().strip()!='---':return None
            for line in stream:
                size+=len(line)
                if size>32000000:return None
                if line.strip()=='---':break
                if not line.startswith('messages:'):header.append(line)
            else:return None
        fm,_=parse_frontmatter('---\n'+''.join(header)+'---\n')
        if withheld(fm):return None
        if fm.get('imported_note') and note(Path(root)/str(fm['imported_note']),root,explicit=True,headers_only=True) is None:return None
        return fm
    except (OSError,UnicodeError):return None
