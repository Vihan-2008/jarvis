"""Artifacts: everything that has been made, in one library.

A reply that makes something whole (a page, a picture, a diagram, a small app, a document, slides, a sheet, a chart)
shows it beside its chat. That was the only place it could be found again: in the chat that made it. This keeps all of
them, from every chat, in one place, each with its versions. Its owner can also make things here directly (a
whiteboard, an empty document, slides or sheet) and change them.

The rules this file keeps:

- A version is never rewritten or dropped by a later one. Going back to an earlier version adds it again as the newest.
  (The one exception is its owner's own work in progress: while they are drawing or typing, the same version is kept
  up to date instead of a new one being added every few seconds.)
- What a chat made is found again by reading the chat, with the same rule the window uses to show it (a fenced block
  of a kind that can be shown, long enough to be a thing rather than a snippet, named the same way). Chats marked
  private are never read, and what a deleted chat made is no longer listed.
- Everything is kept in the app's own folder on this PC (<state>/artifacts/, one file each), not in the notes vault,
  and anything that looks like a key is hidden before it is written.
- An artifact is data. Nothing in one is ever run here or treated as an instruction.
"""
from __future__ import annotations

import json
import re
import secrets as _rand
import threading
import time

from jcc.redact import redact
from jcc.vault import atomic_write, read_json

ID = re.compile(r"art-\d{8}-\d{6}-[0-9a-f]{4}")
# What a fenced block is, by the language it is written in. (The window has the same table: jcc/static/nova-rich.js.)
KINDS = {"html": "page", "htm": "page", "svg": "picture", "mermaid": "diagram", "jsx": "app", "tsx": "app", "react": "app",
         "markdown": "document", "md": "document", "slides": "slides", "csv": "sheet", "sheet": "sheet", "chart": "data"}
NAMES = {"page": "Page", "picture": "Picture", "diagram": "Diagram", "app": "App", "document": "Document", "slides": "Slides",
         "sheet": "Sheet", "data": "Chart", "whiteboard": "Whiteboard"}
LANGS = {"page": "html", "picture": "svg", "diagram": "mermaid", "app": "jsx", "document": "markdown", "slides": "slides",
         "sheet": "csv", "data": "chart", "whiteboard": "whiteboard"}
# Lines: anything shorter is a snippet, not a thing (others: 6). A chart or slides are written under their own word,
# so even one line of them is the thing itself.
SHORTEST = {"document": 10, "sheet": 3, "data": 1, "slides": 1}
LONGEST = 1_500_000            # characters in one version
VERSIONS = 200                 # kept for one artifact; beyond that the oldest after the first makes room
MOST = 5000                    # artifacts kept in all
WORKING = 600.0                # seconds its owner's own latest version counts as work in progress
AT_ONCE = 40                   # chats read in one go when catching up

_lock = threading.RLock()


class ArtifactError(ValueError):
    """Something the owner can be told as it is."""


# ---------------------------------------------------------------------- what a reply made
_FENCE = re.compile(r"^\s*```\s*([^\s`]*)[ \t]*(.*)$")
_CLOSE = re.compile(r"^\s*```\s*$")
_NAMED = re.compile(r"^\s*(?:\*\*)?(?:File|Artifact|Title)(?:\*\*)?:\s*(?:\*\*)?\s*`?([^`*]{2,80}?)`?(?:\*\*)?\s*$", re.I)
_HEADING = re.compile(r"^(#{1,4})\s+(.+)$")
_RULE = re.compile(r"^\s*([-*_])\s*\1\s*\1[\s\-*_]*$")
_QUOTE = re.compile(r"^\s*>\s?")
_TABLE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_MORE = re.compile(r"^\s{2,}\S")
_WORDS = r"([^<>\n]{2,80}?)"


def _name(kind: str, info: str, code: str, given: str) -> str:
    info = info.strip()
    said = re.search(r"(?:title|name)=[\"'](.{1,80}?)[\"']", info, re.I)
    said = said.group(1) if said else (info if re.fullmatch(r"[\w .()-]{2,60}\.\w{1,5}", info) else "") or given
    if kind in ("document", "slides"):
        found = re.search(r"^#{1,3}\s+(.{2,80})$", code, re.M)
    elif kind == "app":
        found = re.search(r"(?:function|const|class)\s+([A-Z]\w{1,40})", code)
    elif kind == "data":
        found = re.search(r"\"title\"\s*:\s*\"" + _WORDS + "\"", code)
    elif kind in ("page", "picture"):
        found = re.search("<title>" + _WORDS + "</title>", code, re.I) or re.search(r"<h1[^&<>\"']*>" + _WORDS + "</h1>", code, re.I)
    else:
        found = None
    inside = found.group(1) if found else ""
    if kind in ("page", "picture"):
        inside = _plain(inside)                       # (a title is written "Rise &amp; Shine" in a page's code)
    name = re.sub(r"[*`]", "", str(said or inside or NAMES[kind])).strip()[:80]
    return name or NAMES[kind]


def found_in(text: str) -> list[dict]:
    """What a reply made, in order: [{kind, lang, name, code}]. The same reading the window gives the reply."""
    lines, out, i = str(text or "").replace("\r\n", "\n").split("\n"), [], 0
    para: list[str] = []
    last = None                       # the block before this one: a paragraph's lines, or "other"

    def flush():
        nonlocal para, last
        if para:
            last, para = list(para), []

    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line)
        if m:
            code, closed = [], False
            i += 1
            while i < len(lines):
                if _CLOSE.match(lines[i]):
                    closed = True
                    i += 1
                    break
                code.append(lines[i])
                i += 1
            lang = re.sub(r"[^\w+#.-]", "", (m.group(1) or "text").lower())[:20] or "text"
            if para:
                label = _NAMED.match(para[-1])
            elif isinstance(last, list) and len(last) == 1:
                label = _NAMED.match(re.sub(r"\*\*|[*`]", "", last[0]))
            else:
                label = None
            kind = KINDS.get(lang)
            made = closed and kind and len(code) >= SHORTEST.get(kind, 6)
            if made and label:
                if para:
                    para.pop()
                else:
                    last = "other"
            flush()
            last = "other"
            if made:
                body = "\n".join(code)
                out.append({"kind": kind, "lang": lang, "name": _name(kind, m.group(2) or "", body, label.group(1) if label else ""), "code": body})
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        if _HEADING.match(line) or _RULE.match(line):
            flush()
            last = "other"
            i += 1
            continue
        if _QUOTE.match(line):
            flush()
            last = "other"
            while i < len(lines) and _QUOTE.match(lines[i]):
                i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE.match(lines[i + 1]):
            flush()
            last = "other"
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                i += 1
            continue
        if _ITEM.match(line):
            flush()
            last = "other"
            while i < len(lines) and _ITEM.match(lines[i]):
                i += 1
                while i < len(lines) and _MORE.match(lines[i]) and not _ITEM.match(lines[i]) and not re.match(r"^\s*```", lines[i]):
                    i += 1
            continue
        para.append(line)
        i += 1
    return out


# ---------------------------------------------------------------------- the library on disk
def _folder(cfg):
    return cfg.state_dir / "artifacts"


def _path(cfg, ident):
    ident = str(ident or "")
    if not ID.fullmatch(ident):
        raise ArtifactError("That is not something in the library.")
    return _folder(cfg) / (ident + ".json")


def _plain(text: str) -> str:
    """The few characters a page's own code writes as entities, as the characters they stand for."""
    return re.sub(r"&(amp|lt|gt|quot|#39|nbsp);", lambda m: {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "#39": "'", "nbsp": " "}[m.group(1)], text)


def _peek(kind: str, code: str) -> str:
    """A few words of what is in it, for its card and for searching: the words on a board, a chart's labels, what a
    page says (not its tags), a sheet's first rows."""
    try:
        if kind == "whiteboard":
            items = [i for i in json.loads(code).get("items") or [] if isinstance(i, dict)]
            words = [str(i.get("text")) for i in items if i.get("t") in ("text", "note") and i.get("text")]
            text = " \u00b7 ".join(words) if words else (f"A drawing of {len(items)} mark{'' if len(items) == 1 else 's'}" if items else "An empty board")
        elif kind == "data":
            data = json.loads(code)
            names = [str(s.get("name")) for s in data.get("series") or [] if isinstance(s, dict) and s.get("name")]
            text = ", ".join(str(x) for x in (data.get("x") or [])[:14]) + (" (" + ", ".join(names[:4]) + ")" if names else "")
        elif kind in ("page", "picture", "app"):
            text = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", code)
            text = _plain(re.sub(r"<[^>]{0,2000}>|[{}]|^\s*import\b.*$|\bexport\s+(default\s+)?", " ", text, flags=re.M))
        elif kind == "sheet":
            text = " \u00b7 ".join(line.replace(",", ", ") for line in code.split("\n")[:4])
        elif kind == "diagram":
            labels = list(dict.fromkeys(re.findall(r"[\[({]+\s*\"?([^\[\](){}\"\n]{2,40})\"?\s*[\])}]+", code)))
            text = " \u2192 ".join(labels[:10]) if labels else code
        else:
            text = re.sub(r"[*_`|]", "", re.sub(r"(?m)^\s*(#{1,6}|[-*+]|\d+[.)]|>|-{3,})\s*", "", code))
    except (ValueError, TypeError, AttributeError):
        text = code
    return " ".join(str(text).split())[:300]


def _summary(record: dict) -> dict:
    latest = record["versions"][-1]
    return {"id": record["id"], "title": record["title"], "kind": record["kind"], "lang": record["lang"], "created": record["created"],
            "updated": latest["at"], "chat": record.get("chat", ""), "starred": record.get("starred") is True, "versions": len(record["versions"]),
            "yours": any(v.get("by") == "you" for v in record["versions"]), "size": len(latest["code"]), "peek": _peek(record["kind"], latest["code"]),
            "key": record.get("key", "")}


def _index(cfg) -> dict:
    """{id: summary}. Made again from the files themselves if it is missing or damaged."""
    with _lock:
        found = read_json(_folder(cfg) / "index.json", None)
        if isinstance(found, dict) and all(isinstance(v, dict) for v in found.values()):
            return found
        found = {}
        for path in _folder(cfg).glob("art-*.json") if _folder(cfg).exists() else []:
            record = read_json(path, {})
            if ID.fullmatch(path.stem) and record.get("id") == path.stem and record.get("versions"):
                try:
                    found[path.stem] = _summary(record)
                except (KeyError, TypeError):
                    continue
        if found:
            atomic_write(_folder(cfg) / "index.json", json.dumps(found))
        return found


def _save(cfg, record: dict) -> dict:
    with _lock:
        index = _index(cfg)
        _folder(cfg).mkdir(parents=True, exist_ok=True)
        atomic_write(_path(cfg, record["id"]), json.dumps(record))
        index[record["id"]] = _summary(record)
        atomic_write(_folder(cfg) / "index.json", json.dumps(index))
        return record


GONE = "That is no longer in the library."


def _load(cfg, ident) -> dict:
    """A record as it is kept, whatever has become of its chat. (For the library's own housekeeping only.)"""
    record = read_json(_path(cfg, ident), {})
    if record.get("id") != ident or not isinstance(record.get("versions"), list) or not record["versions"]:
        raise ArtifactError(GONE)
    return record


def _shut(cfg, cid) -> bool:
    """Whether what a chat made may not be shown just now: the chat has been deleted, or it is marked private."""
    if not cid:
        return False                                  # made by hand: no chat to answer for it
    from jcc.chats import Chats
    chats = Chats(cfg)
    try:
        return chats.is_deleted(str(cid)) or chats.withheld(str(cid))
    except OSError:
        return True                                   # cannot be told this moment: not shown until it can


def _read(cfg, ident) -> dict:
    """A record its owner may see. What is not listed cannot be had by its id either: something from a deleted or a
    private chat is answered exactly as something that was never there, so an id tells nothing by itself."""
    record = _load(cfg, ident)
    if _shut(cfg, record.get("chat")):
        raise ArtifactError(GONE)
    return record


def _text(code) -> str:
    code = str(code if code is not None else "").replace("\r\n", "\n")
    if len(code) > LONGEST:
        raise ArtifactError("That is too large to keep as one thing.")
    return redact(code)


def _title(title, kind: str) -> str:
    return redact(" ".join(str(title or "").split()))[:120] or NAMES[kind]


def _add(record: dict, code: str, by: str, at: float, note: str = "") -> bool:
    """A new version, unless it is the same as the one before it. True when one was added."""
    versions = record["versions"]
    if versions and versions[-1]["code"] == code:
        return False
    versions.append({"n": (versions[-1]["n"] + 1) if versions else 1, "at": at, "by": by, "note": note[:200], "code": code})
    if len(versions) > VERSIONS:
        del versions[1]                               # the first is kept: it is where the thing began
    return True


def _new(cfg, title: str, kind: str, lang: str, chat: str = "", key: str = "") -> dict:
    if len(_index(cfg)) >= MOST:
        raise ArtifactError("The library is full. Remove something you no longer need.")
    ident = "art-" + time.strftime("%Y%m%d-%H%M%S") + "-" + _rand.token_hex(2)
    return {"id": ident, "title": title, "name": title, "kind": kind, "lang": lang, "created": time.time(), "chat": chat, "key": key, "starred": False,
            "imported": 0, "versions": []}


# ---------------------------------------------------------------------- what the chats have made
def _hidden(cfg) -> set[str]:
    """The chats whose things are not listed: deleted ones."""
    from jcc.chats import Chats
    try:
        return Chats(cfg).deleted_ids()
    except OSError:
        return set()


def sync_chat(cfg, chat: dict) -> list[str]:
    """Bring in what one chat has made. Returns the ids of what is new or has a new version."""
    cid, groups = str(chat.get("id") or ""), {}
    for message in chat.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for block in found_in(str(message.get("content") or "")):
            groups.setdefault(block["kind"] + "\n" + block["name"].lower(), []).append({**block, "at": message.get("at")})
    changed = []
    with _lock:
        mine = {row["key"]: ident for ident, row in _index(cfg).items() if row.get("chat") == cid and row.get("key")}
        removed = read_json(_folder(cfg) / "removed.json", {})
        for key, blocks in groups.items():
            try:
                record = _load(cfg, mine[key]) if key in mine else None
            except ArtifactError:
                record = None
            fresh = record is None
            if fresh:
                # Something its owner took out of the library comes back only when the chat makes a newer version of it.
                gone = removed.get(cid + "\n" + key)
                if isinstance(gone, int) and len(blocks) <= gone:
                    continue
                try:
                    record = _new(cfg, _title(blocks[0]["name"], blocks[0]["kind"]), blocks[0]["kind"], blocks[0]["lang"], cid, key)
                except ArtifactError:
                    break                             # the library is full: nothing more is brought in
                record["imported"] = gone if isinstance(gone, int) else 0
            seen, added = int(record.get("imported") or 0), False
            for block in blocks[seen:]:
                try:
                    code = _text(block["code"])
                except ArtifactError:
                    continue
                when = float(block["at"]) if isinstance(block.get("at"), (int, float)) else time.time()
                if _add(record, code, "jarvis", when):
                    added, record["lang"] = True, block["lang"]
            if len(blocks) != seen or fresh:
                record["imported"] = len(blocks)
                if record["versions"]:
                    _save(cfg, record)
                    if added:
                        changed.append(record["id"])
    return changed


def _take_out(cfg, cid: str) -> None:
    """What was brought in from one chat is taken out again. (Its owner's own versions of a thing are theirs: a thing
    they have changed stays.)"""
    for ident, known in list(_index(cfg).items()):
        if known.get("chat") == cid and not known.get("yours"):
            _forget(cfg, ident)


def _private(cfg, chats, cid: str) -> bool:
    """Whether a chat is still there but may not be read (it has been marked private)."""
    try:
        if not (cfg.vault / "Conversations" / (cid + ".md")).exists():
            return False                              # the chat itself is gone: what it made is all that is left of it, and stays
        chats.get(cid)
    except ValueError:
        return True
    except OSError:
        return False
    return False


def sync(cfg, most: int = AT_ONCE) -> dict:
    """Catch up with the chats that have changed since they were last read, a few at a time. {"more": whether any are left}."""
    from jcc.chats import Chats
    chats = Chats(cfg)
    with _lock:
        marks = read_json(_folder(cfg) / "chats.json", {})
        rows = chats.list()
        # A chat marked private since it was read is no longer among the chats: what came from it is taken out again.
        gone = False
        for cid in {str(row.get("chat")) for row in _index(cfg).values() if row.get("chat")} - {row.get("id") for row in rows} - _hidden(cfg):
            if _private(cfg, chats, cid):
                _take_out(cfg, cid)
                gone = marks.pop(cid, None) is not None or gone
        todo = [row for row in rows if row.get("id") and marks.get(row["id"]) != row.get("updated")]
        for row in todo[:most]:
            try:
                sync_chat(cfg, chats.get(row["id"]))
            except ValueError:
                _take_out(cfg, row["id"])             # it may not be read (private): nothing of it is kept here
            except OSError:
                continue                              # cannot be read this moment: tried again next time
            marks[row["id"]] = row.get("updated")
        if todo or gone:
            _folder(cfg).mkdir(parents=True, exist_ok=True)
            atomic_write(_folder(cfg) / "chats.json", json.dumps(marks))
    return {"more": len(todo) > most}


def find(cfg, chat: str, kind: str, name: str) -> dict | None:
    """The library's own record of something a chat made (the chat is read first, so a reply that has just ended is in)."""
    from jcc.chats import CHAT_ID, Chats
    if not CHAT_ID.fullmatch(str(chat or "")) or _shut(cfg, chat):
        return None                                   # (a deleted chat is not read for the library, and a private one never)
    try:
        sync_chat(cfg, Chats(cfg).get(chat))
    except (ValueError, OSError):
        return None
    key = str(kind) + "\n" + str(name).lower()
    ident = next((i for i, row in _index(cfg).items() if row.get("chat") == chat and row.get("key") == key), None)
    try:
        return get(cfg, ident) if ident else None
    except ArtifactError:
        return None


def locate(cfg, ident: str, code) -> int | None:
    """Where in a thing's history a given text is: the place (0 is the oldest) of the newest version that holds exactly
    it, or None."""
    try:
        record, wanted = _read(cfg, ident), _text(code)
    except ArtifactError:
        return None
    return next((i for i in range(len(record["versions"]) - 1, -1, -1) if record["versions"][i]["code"] == wanted), None)


# ---------------------------------------------------------------------- what its owner does
def listing(cfg, query: str = "", kind: str = "", only: str = "") -> list[dict]:
    """What is in the library, newest first. only: "" (all), "starred" or "yours"."""
    words, shut = [w for w in str(query or "").lower().split() if w][:8], {}
    rows = []
    for row in _index(cfg).values():
        cid = row.get("chat")
        if cid and cid not in shut:
            shut[cid] = _shut(cfg, cid)               # (asked once for each chat: its header is read only when the note has changed)
        if (cid and shut[cid]) or (kind and row.get("kind") != kind):
            continue
        if (only == "starred" and not row.get("starred")) or (only == "yours" and not row.get("yours")):
            continue
        text = (str(row.get("title")) + " " + NAMES.get(row.get("kind"), "") + " " + str(row.get("peek"))).lower()
        if all(word in text for word in words):
            rows.append({k: v for k, v in row.items() if k != "key"})
    return sorted(rows, key=lambda r: (float(r.get("updated") or 0), r["id"]), reverse=True)


def get(cfg, ident: str) -> dict:
    """One thing: what it is, its versions (when, by whom, how large), and what the newest one holds. An earlier
    version's own text is asked for by itself (version), so a long history is not sent whole every time."""
    record = _read(cfg, ident)
    return {**{k: record.get(k) for k in ("id", "title", "kind", "lang", "created", "chat")}, "starred": record.get("starred") is True,
            "versions": [{"n": v.get("n"), "at": v.get("at"), "by": v.get("by"), "note": v.get("note") or "", "size": len(v.get("code") or "")} for v in record["versions"]],
            "code": record["versions"][-1]["code"]}


def version(cfg, ident: str, number) -> dict:
    record = _read(cfg, ident)
    found = next((v for v in record["versions"] if v.get("n") == number), None)
    if found is None:
        raise ArtifactError("That version is not there.")
    return {"id": ident, "n": found["n"], "code": found["code"]}


def save(cfg, ident: str = "", title: str = "", kind: str = "", lang: str = "", code: str = "", note: str = "", amend: bool = False) -> dict:
    """Something its owner made, or a change of theirs to something that is here. amend: this is work in progress (the
    same version of theirs is kept up to date for a few minutes instead of one being added each time)."""
    code = _text(code)
    if not code.strip():
        raise ArtifactError("There is nothing in it yet.")
    with _lock:
        if ident:
            record = _read(cfg, ident)
        else:
            if kind not in NAMES:
                raise ArtifactError("That is not a kind of thing the library keeps.")
            lang = str(lang or "").lower()
            if kind == "whiteboard" or KINDS.get(lang) != kind:
                lang = LANGS[kind]
            record = _new(cfg, _title(title, kind), kind, lang)
        latest = record["versions"][-1] if record["versions"] else None
        now = time.time()
        if amend and latest and latest.get("by") == "you" and now - float(latest.get("at") or 0) < WORKING and not latest.get("note"):
            latest.update(code=code, at=now)
        else:
            _add(record, code, "you", now, redact(" ".join(str(note or "").split())))
        if not ident and title:
            record["title"] = _title(title, record["kind"])
        _save(cfg, record)
    return get(cfg, record["id"])


def restore(cfg, ident: str, number) -> dict:
    """Go back to an earlier version: it is added again as the newest, and the chat that made the thing is told, so the
    conversation carries on from it."""
    with _lock:
        record = _read(cfg, ident)
        old = next((v for v in record["versions"] if v.get("n") == number), None)
        if old is None:
            raise ArtifactError("That version is not there.")
        if old is record["versions"][-1] or not _add(record, old["code"], "you", time.time(), f"Version {old['n']}, brought back"):
            raise ArtifactError("That is already what the current version holds.")
        _save(cfg, record)
    told = False
    # The chat that made it is told, in the form it reads its own work in (a block under the same name), so that the
    # next change asked for there is made to this version. (Not when the text holds a line that would end the block.)
    if record.get("chat") and record.get("key") and not re.search(r"^\s*```\s*$", old["code"], re.M):
        from jcc.chats import Chats
        words = (f"The owner went back to version {old['n']} of “{record['title']}”. It is the current version again.\n\n"
                 f"File: {record.get('name') or record['title']}\n```{record['lang']}\n{old['code']}\n```")
        try:
            Chats(cfg).update(record["chat"], message={"role": "assistant", "content": words, "status": "done", "agent": "jarvis", "restored": True})
            told = True
        except (ValueError, OSError):
            told = False                              # the chat is gone or private: the library still has the version
    return {**get(cfg, ident), "told": told}


def rename(cfg, ident: str, title: str) -> dict:
    with _lock:
        record = _read(cfg, ident)
        if not str(title or "").strip():
            raise ArtifactError("Give it a name.")
        record["title"] = _title(title, record["kind"])
        _save(cfg, record)
    return get(cfg, ident)


def star(cfg, ident: str, on: bool) -> dict:
    with _lock:
        record = _read(cfg, ident)
        record["starred"] = on is True
        _save(cfg, record)
    return get(cfg, ident)


def _forget(cfg, ident: str) -> None:
    with _lock:
        index = _index(cfg)
        _path(cfg, ident).unlink(missing_ok=True)
        if index.pop(ident, None) is not None:
            atomic_write(_folder(cfg) / "index.json", json.dumps(index))


def remove(cfg, ident: str) -> dict:
    """Take it out of the library. (What a chat made stays in that chat's own text: only this copy and its history go.)"""
    with _lock:
        record = _read(cfg, ident)                    # (what is not shown is not removed by its id either: it comes back with its chat)
        _forget(cfg, ident)
        if record.get("chat") and record.get("key"):
            # Not brought in again by itself the next time that chat is read.
            gone = read_json(_folder(cfg) / "removed.json", {})
            gone[record["chat"] + "\n" + record["key"]] = int(record.get("imported") or 0)
            atomic_write(_folder(cfg) / "removed.json", json.dumps(gone))
    return {"removed": ident}
