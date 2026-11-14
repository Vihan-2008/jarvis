"""Vault file access. All writes go through redaction; Private/ notes are never released for AI use."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jcc.redact import redact

FOLDERS = ["Requests", "Reports", "Research", "Conversations", "Jobs", "System", "Private"]
_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


class PrivateNoteError(PermissionError):
    """Raised when code tries to hand a Private/ note to an AI model."""


@dataclass
class Note:
    path: Path
    rel: str
    frontmatter: dict[str, Any]
    body: str


def yaml_value(v: Any) -> str:
    """Render a value as YAML. JSON scalars/lists are valid YAML, and quoting blocks injection."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return json.dumps([redact(str(x)) if isinstance(x, str) else x for x in v],
                          ensure_ascii=False)
    return json.dumps(redact(str(v)), ensure_ascii=False)


def render_note(frontmatter: dict[str, Any], body: str) -> str:
    lines = ["---"] + [f"{k}: {yaml_value(v)}" for k, v in frontmatter.items()] + ["---", ""]
    return "\n".join(lines) + redact(body).rstrip() + "\n"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    fm: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "-", "#")):
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        try:
            fm[k.strip()] = json.loads(v) if v else ""
        except json.JSONDecodeError:
            fm[k.strip()] = v.strip("'\"")
    return fm, text[m.end():]


def read_json(path, default):
    """What a saved JSON file holds, or `default` if it is missing, half-written, damaged, or not the kind of thing expected.

    The app has to keep working when one of its files, or another program's, cannot be read at the moment."""
    try:
        value = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return default
    return value if default is None or isinstance(value, type(default)) else default


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(redact(text))
        # On Windows a file cannot be replaced at the very moment another program, or another part of JARVIS, is reading
        # it ("Access is denied"). It is free again a moment later, so try a few times before giving up.
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.03 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"path escapes the vault: {rel}")
        return p

    def ensure_structure(self) -> None:
        for f in FOLDERS:
            (self.root / f).mkdir(parents=True, exist_ok=True)

    def write(self, rel: str, text: str) -> Path:
        p = self.path(rel)
        atomic_write(p, text)
        return p

    def read(self, rel: str) -> str | None:
        p = self.path(rel)
        return p.read_text("utf-8") if p.exists() else None

    @staticmethod
    def is_private_rel(rel: str) -> bool:
        first = rel.replace("\\", "/").lstrip("/").split("/", 1)[0]
        return any(p.lower()=='private' for p in rel.replace('\\','/').split('/'))

    def notes(self) -> list[Note]:
        out = []
        for p in self.root.rglob("*.md"):
            rel = p.relative_to(self.root).as_posix()
            from jcc.privacy import safe_path, withheld
            if not safe_path(p,self.root):
                continue
            try:
                fm, body = parse_frontmatter(p.read_text("utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if withheld(fm):
                continue                              # marked private in its own header: not searched and not quoted, like one in a Private folder
            out.append(Note(p, rel, fm, body))
        return out

    def find_note(self, name: str) -> Note | None:
        """Resolve filenames first, avoiding reads of unrelated archive and private bodies."""
        from jcc.privacy import note
        target=name.strip().strip('[]').split('|')[0].removesuffix('.md').lower()
        if not target:return None
        candidates=[]
        for p in self.root.rglob('*.md'):
            rel=p.relative_to(self.root).as_posix();stem=p.stem.lower()
            score=0 if rel.lower().removesuffix('.md')==target else 1 if stem==target else 2 if target in stem else 3
            if score<3:candidates.append((score,rel,p))
        for _,rel,p in sorted(candidates):
            value=note(p,self.root,explicit=True)
            if value is None:return Note(p,rel,{'private':True},'')
            fm,body=value;return Note(p,rel,fm,body)
        return None

    def note_for_ai(self, name: str) -> Note | None:
        """The ONLY way notes reach an AI model. Private notes are refused."""
        n = self.find_note(name)
        if n is None:
            return None
        if self.is_private_rel(n.rel) or n.frontmatter.get("private") in (True, "true", "yes"):
            raise PrivateNoteError(f"{n.rel} is private and is never sent to an AI model")
        return n
