"""Project-linked chats. Obsidian Markdown is the source of truth."""
from __future__ import annotations

import os
import re
import json
import time
from pathlib import Path

from jcc import receipts
from jcc.config import Config
from jcc.lock import InstanceLock
from jcc.redact import redact
from jcc.vault import Vault, parse_frontmatter, render_note

CHAT_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4,12}$")
_SEEN: dict[str, tuple] = {}   # chat note -> (its signature, the linked note and its signature, what was read, when)


class _Folders:
    """When each note in a folder last changed, learned from one listing of the folder instead of one question per note."""

    def __init__(self, vault: Path):
        self.vault, self.seen = vault, {}

    def stamp(self, note: str) -> str:
        folder, _, name = note.replace("\\", "/").rpartition("/")
        table = self.seen.get(folder)
        if table is None:
            table = self.seen[folder] = {}
            try:
                with os.scandir(self.vault / folder) as rows:
                    for row in rows:
                        try:
                            status = row.stat()
                            table[os.path.normcase(row.name)] = f"{status.st_mtime_ns}:{status.st_size}"
                        except OSError:
                            continue
            except OSError:
                pass
        return table.get(os.path.normcase(name), "missing")


def _metadata(path: Path, signature: str, vault: Path, folders: _Folders):
    """The header of a chat note, read again only when the note (or the imported note it points to) has changed.

    Listing chats is asked for every few seconds; reading hundreds of notes each time made the whole app sluggish."""
    from jcc.privacy import chat_metadata
    key = str(path)
    known = _SEEN.get(key)
    if known and known[0] == signature:
        linked, linked_stamp, metadata, at = known[1], known[2], known[3], known[4]
        if metadata is None:
            if time.time() - at < 60:          # hidden (private): look again once a minute in case that changed
                return None
        elif not linked or folders.stamp(linked) == linked_stamp:
            return metadata
    metadata = chat_metadata(path, vault)
    linked = str(metadata.get("imported_note") or "") if metadata else ""
    if len(_SEEN) > 20000:
        _SEEN.clear()
    _SEEN[key] = (signature, linked, folders.stamp(linked) if linked else "", metadata, time.time())
    return metadata


class Chats:
    def __init__(self, cfg: Config):
        self.cfg, self.vault = cfg, Vault(cfg.vault)

    def get(self, cid: str) -> dict:
        if not CHAT_ID.fullmatch(cid):
            raise ValueError("Invalid chat.")
        text = self.vault.read(f"Conversations/{cid}.md")
        if text is None:
            raise ValueError("Chat not found.")
        fm, _ = parse_frontmatter(text)
        from jcc.privacy import withheld,note as eligible_note
        # The same rule the list of chats goes by: a chat that is not listed cannot be had by its id either.
        if withheld(fm) or fm.get("imported_note") and eligible_note(self.cfg.vault/str(fm["imported_note"]),self.cfg.vault,explicit=True,headers_only=True) is None:
            raise ValueError("This chat is marked private.")
        return fm

    def is_deleted(self, cid: str) -> bool:
        return bool(CHAT_ID.fullmatch(str(cid or ""))) and (self.cfg.state_dir / "deleted-chats" / cid).exists()

    def withheld(self, cid: str) -> bool:
        """Whether a chat is there but may not be read (it is marked private). Only its header is looked at, and only
        when the note has changed since it was last looked at. A chat that is not there at all is not withheld."""
        if not CHAT_ID.fullmatch(str(cid or "")):
            return False
        path = self.cfg.vault / "Conversations" / (cid + ".md")
        try:
            status = path.stat()
        except OSError:
            return False
        return _metadata(path, f"{status.st_mtime_ns}:{status.st_size}", self.cfg.vault, _Folders(self.cfg.vault)) is None

    def save(self, chat: dict) -> None:
        chat['has_local_work']=any(m.get('receipt') for m in chat['messages'])
        body = [f"# {chat['title']}", "", f"Project: {chat.get('project') or 'General'}", ""]
        if chat.get("project"):
            body += [f"Memory: [[Projects/{chat['project']}/Memory]]", ""]
        for m in chat["messages"]:
            body += [f"## {m['role'].title()}", "", m["content"], ""]
            if m.get("receipt"):
                body += [f"[[{receipts.receipt_rel(m['receipt']).removesuffix('.md')}|Job details]] · {m.get('status', '')}", ""]
        self.vault.write(f"Conversations/{chat['id']}.md", render_note(chat, "\n".join(body)))

    def create(self, title: str = "New chat", project: str | None = None, parent: str | None = None) -> dict:
        """A new chat. parent: the Master chat it belongs to (a piece of work the agents do for a request made there)."""
        if project and project not in self.cfg.projects:
            raise ValueError("Project not found.")
        if parent is not None and not CHAT_ID.fullmatch(str(parent)):
            raise ValueError("Invalid chat.")
        chat = {"id": receipts.new_id(), "title": redact(title.strip()[:100] or "New chat"),
                "project": project, "updated": time.time(), "messages": []}
        if parent:
            chat["parent"] = parent
        self.save(chat)
        return chat

    def deleted_ids(self):
        folder = self.cfg.state_dir / "deleted-chats"
        return {p.name for p in folder.glob("*") if CHAT_ID.fullmatch(p.name)}

    def set_deleted(self, cid, deleted):
        if not CHAT_ID.fullmatch(cid):
            raise ValueError("Invalid chat.")
        folder = self.cfg.state_dir / "deleted-chats"
        marker = folder / cid
        if deleted:
            self.get(cid)
            folder.mkdir(parents=True, exist_ok=True)
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
        return {"id": cid, "deleted": deleted}

    def list(self) -> list[dict]:
        from jcc.vault import atomic_write
        cache_path=self.cfg.state_dir/'conversation-index.json'
        try:cached=json.loads(cache_path.read_text('utf-8')) if cache_path.exists() else {}
        except (OSError,ValueError):cached={}
        current={};out=[];folders=_Folders(self.cfg.vault)
        deleted = self.deleted_ids()
        try:entries=[e for e in os.scandir(self.cfg.vault/'Conversations') if e.name.endswith('.md')]
        except OSError:entries=[]
        for entry in entries:
            stem=entry.name[:-3]
            if stem in deleted or not CHAT_ID.fullmatch(stem):continue
            try:
                status=entry.stat()
                signature=str(status.st_mtime_ns)+':'+str(status.st_size)
                metadata=_metadata(Path(entry.path),signature,self.cfg.vault,folders)
                if metadata is None:continue
                local=metadata.get('has_local_work')
                if local is None:
                    prior=cached.get(stem,{})
                    local=prior.get('has_local_work') if prior.get('signature')==signature else any(m.get('receipt') for m in self.get(stem).get('messages',[]))
                row={k:metadata.get(k) for k in ('id','title','project','updated','source','source_id','archived','parent')}
                row['workspace']=not metadata.get('archived') and (metadata.get('pinned') or not metadata.get('source') or bool(metadata.get('project')) or bool(local))
                out.append(row);current[stem]={'signature':signature,'has_local_work':bool(local)}
            except (ValueError,OSError):continue
        if current!=cached:atomic_write(cache_path,json.dumps(current))
        return sorted(out,key=lambda c:c.get('updated') or 0,reverse=True)

    def update(self, cid: str, *, project=None, title=None, message=None, archived=None, careful=None, summary=None) -> dict:
        lock = InstanceLock(self.cfg.state_dir / f"chat-{cid}.lock")
        if not CHAT_ID.fullmatch(cid):
            raise ValueError("Invalid chat.")
        acquired = False
        for _ in range(100):
            if lock.acquire():
                acquired = True
                break
            time.sleep(0.05)
        if not acquired:
            raise ValueError("Chat is being updated. Try again.")
        try:
            chat = self.get(cid)
            if project is not None:
                if project != "none" and project not in self.cfg.projects:
                    raise ValueError("Project not found.")
                if chat.get("project") and chat["messages"] and (None if project == "none" else project) != chat.get("project"):
                    raise ValueError("Start a new chat to switch projects after messages have been sent.")
                chat["project"] = None if project == "none" else project
            if title is not None:
                chat["title"] = redact(str(title).strip()[:100] or "New chat")
            if isinstance(careful, dict):
                chat["careful"], chat["own_data"] = careful.get("exposed") is True, careful.get("private") is True
            if isinstance(summary, dict):
                # A compacted conversation: what was said up to message number `upto`, in a few lines. The messages stay.
                chat["summary"], chat["summary_upto"] = redact(str(summary.get("text", "")))[:6000], int(summary.get("upto") or 0)
            if archived is not None:
                if not isinstance(archived, bool):
                    raise ValueError("Archive must be true or false.")
                chat["archived"] = archived
                chat["pinned"] = not archived
            if message:
                message = dict(message)
                message.setdefault("at", time.time())
                message["content"] = redact(message["content"])
                existing = next((m for m in chat["messages"] if message.get("receipt") and
                                 m.get("receipt") == message["receipt"] and m["role"] == message["role"]), None)
                if existing:
                    if not (existing.get("status") in ("done", "failed", "needs_approval", "paused", "cancelled") and
                            message.get("status") in ("running", "queued") and not message.get("resume_requested")):
                        existing.update(message)
                else:
                    chat["messages"].append(message)
                if chat["title"] == "New chat" and message["role"] == "user":
                    chat["title"] = message["content"][:70]
            chat["updated"] = time.time()
            self.save(chat)
        finally:
            lock.discard()
        if message and chat.get("parent") and message.get("receipt") and message.get("role") == "assistant":
            # A piece of work in a chat of its own: its Master chat hears how it is going (its line and its checklist).
            content = str(message.get("content") or "").split("\n\n", 1)[0][:400]
            try:
                self.update(chat["parent"], message={"role": "assistant", "receipt": message["receipt"], "job": True, "child": cid,
                                                     **{k: message[k] for k in ("status", "agent", "model") if message.get(k)},
                                                     **({"stopped": bool(message["stopped"])} if "stopped" in message else {}),
                                                     "content": content or "Working."})
            except (OSError, ValueError):
                pass
        return chat

    def forget(self, cid: str, receipt: str) -> bool:
        """Take one exchange out of a chat again (something overheard that was not meant for JARVIS).
        A chat that was only just created for it, and is empty without it, is removed altogether. Returns whether the chat is gone."""
        lock = InstanceLock(self.cfg.state_dir / f"chat-{cid}.lock")
        if not CHAT_ID.fullmatch(cid) or not receipt:
            raise ValueError("Invalid chat.")
        for _ in range(100):
            if lock.acquire():
                break
            time.sleep(0.05)
        else:
            raise ValueError("Chat is being updated. Try again.")
        try:
            chat = self.get(cid)
            kept = [m for m in chat["messages"] if m.get("receipt") != receipt]
            if len(kept) == len(chat["messages"]):
                return False
            if not kept and not chat.get("source"):
                self.vault.path(f"Conversations/{cid}.md").unlink(missing_ok=True)
                return True
            chat["messages"] = kept
            if chat.get("title") and not any(m["role"] == "user" and m["content"][:70] == chat["title"] for m in kept):
                first = next((m["content"][:70] for m in kept if m["role"] == "user"), "")
                chat["title"] = first or "New chat"
            self.save(chat)
            return False
        finally:
            lock.discard()

    def context(self, cid: str, until: str | None = None) -> str:
        chat = self.get(cid)
        messages = chat["messages"]
        if until:
            end = next((i for i, m in enumerate(messages) if m.get("receipt") == until and m["role"] == "user"), len(messages))
            messages = messages[:end]
        summary = chat.get("summary") if isinstance(chat.get("summary"), str) else ""
        if summary and not until:
            # A compacted conversation: the summary stands for everything up to it; only what came after is quoted.
            try:
                upto = int(chat.get("summary_upto") or 0)
            except (TypeError, ValueError):
                upto = 0
            later = [m for m in messages[upto:] if m.get("status") not in ("running", "queued") and not m.get("compact")][-4:]
            recent = "\n\n".join(f"{m['role']}: {m['content'][:900]}" for m in later)[-2400:]
            return "Summary of the conversation so far:\n" + summary[:3000] + ("\n\nSince then:\n" + recent if recent else "")
        messages = [m for m in messages if m.get("status") not in ("running", "queued")][-4:]
        return "\n\n".join(f"{m['role']}: {m['content'][:900]}" for m in messages)[-2400:]
