"""Cooperative controls. Only the runner kills the process tree it started."""
import hashlib
import json
import re
import time
from jcc.lock import InstanceLock
from jcc.vault import Vault, atomic_write, parse_frontmatter, render_note
from jcc import receipts


ASKED = "ASKED.md"                    # what a job that stopped to ask wrote down, kept in the job's own folder
ANSWER = "owner-answer.json"          # its owner's yes, waiting to be read by the job when it carries on
NEXT = "owner-next.json"              # what its owner said after stopping it, for the job to take in as it carries on
ID = re.compile(r"\d{8}-\d{6}-[a-f0-9]{4}")
SHOWN = 3000                          # characters of a question its owner is shown: a yes is a yes to exactly that much
CUT = "\n(The job wrote more than can be shown. Only what is above was shown to its owner, and only that is answered.)"


def _asks(cfg, rid, fm) -> bool:
    """Whether this record is of a job that stopped to ask. (A record from before jobs said so themselves: it "needs
    approval" and there is no copy of the project with a change in it to review.)"""
    if fm.get("status") != "needs_approval" or fm.get("blocked_by"):
        return False
    return fm.get("asked") is True or ("asked" not in fm and not (cfg.jobs_root / rid / "repo").is_dir())


def question(cfg, rid) -> str | None:
    """What a job that stopped to ask its owner wrote down, or None when it is not waiting for an answer."""
    if not ID.fullmatch(str(rid or "")):
        return None
    text = Vault(cfg.vault).read(f"Jobs/{rid}.md")
    if not text:
        return None
    fm, body = parse_frontmatter(text)
    if not _asks(cfg, rid, fm):
        return None
    for name in (ASKED, "NEEDS_APPROVAL.md"):
        try:
            return (cfg.jobs_root / rid / name).read_text("utf-8", errors="replace")[:20000]
        except OSError:
            continue
    return body[-4000:] or "It stopped and asked for something, but did not say what."


def asked(cfg, rid) -> dict | None:
    """The question of a job that stopped to ask, as its owner is shown it: {"text", "mark"}, or None when it is not
    waiting for an answer. The mark stands for exactly that text. A yes carries it, so that a yes given to one question
    (in a window that has not caught up) is never taken as a yes to the next."""
    from jcc.redact import redact
    text = question(cfg, rid)
    if text is None:
        return None
    text = redact(text).strip()
    if len(text) > SHOWN:
        text = text[:SHOWN].rstrip() + CUT
    return {"text": text, "mark": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]}


def take_answer(workdir) -> dict:
    """The owner's yes to what this job asked, for the job to read as it carries on: {"text": their words, "asked": the
    question as they were shown it}, or {} when there is none. Read once: it is put aside as it is taken."""
    path = workdir / ANSWER
    try:
        saved = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    try:
        path.replace(workdir / ("owner-answer-read-%d.json" % int(time.time())))
    except OSError:
        path.unlink(missing_ok=True)
    try:
        (workdir / ASKED).replace(workdir / ("asked-%d.md" % int(time.time())))        # (kept as a record; the next question is a new file)
    except OSError:
        pass
    if saved.get("yes") is not True:
        return {}
    return {"text": str(saved.get("text") or "Yes.")[:2000], "asked": str(saved.get("asked") or "")[:SHOWN + len(CUT)]}


def answer(cfg, rid, yes: bool, text: str = "", mark: str | None = None) -> dict:
    """Its owner answers a job that stopped to ask. Yes: the same job carries on (its own copy of the project, the same
    agent session) with those words. No: it ends, and nothing is changed. An answer is taken once: a second one, or an
    answer to a job that is not asking, is refused. mark: which question is being answered (asked()["mark"]); a yes
    that carries the mark of another question than the one the job is asking now is refused."""
    from jcc.redact import redact
    from jcc.resilience import child_alive
    if not ID.fullmatch(str(rid or "")):
        raise ValueError("Invalid job.")
    words = redact(" ".join(str(text or "").split()))[:2000]
    vault, work = Vault(cfg.vault), cfg.jobs_root / rid
    if not vault.read(f"Jobs/{rid}.md"):
        raise ValueError("Job not found.")
    work.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(work / "job.lock")
    if not lock.acquire():
        raise ValueError("The job is still stopping. Try again in a moment.")
    try:
        fm, body = parse_frontmatter(vault.read(f"Jobs/{rid}.md") or "")       # (read again inside the lock: one answer, once)
        if not _asks(cfg, rid, fm):
            raise ValueError("This job is not waiting for an answer." if fm.get("status") != "needs_approval" else
                             "This job has a change waiting for your review: approve it or leave it there.")
        if child_alive(work):
            raise ValueError("An earlier agent process of this job is still active. Try again in a moment.")
        now = asked(cfg, rid) or {"text": "", "mark": ""}
        if yes and mark is not None and mark != now["mark"]:
            raise ValueError("This job is asking something else now. Read its question again before you answer.")
        if yes:
            atomic_write(work / ANSWER, json.dumps({"yes": True, "text": words, "asked": now["text"], "at": time.time()}))
            atomic_write(work / "control.json", json.dumps({"action": "resume", "at": time.time()}))
            fm.update(status="queued", asked=False, answered_at=time.time())
            said = "You said yes" + (": \u201c" + words + "\u201d" if words else "") + ". The same job carries on from where it stopped."
        else:
            fm.update(status="cancelled", asked=False, declined=words or "No.", answered_at=time.time())
            said = "You said no" + (": \u201c" + words + "\u201d" if words else "") + ". The job has ended and nothing was changed."
        vault.write(f"Jobs/{rid}.md", render_note(fm, body))
    finally:
        lock.release()
    receipts.update_status(vault, rid, fm["status"])
    if fm.get("chat_id"):
        from jcc.chats import Chats
        try:
            Chats(cfg).update(fm["chat_id"], message={"role": "assistant", "receipt": rid, "status": fm["status"], "content": said, "resume_requested": yes})
        except (ValueError, OSError):
            pass                                  # the chat is gone: the job is answered all the same
    return {"status": fm["status"], "answered": "yes" if yes else "no"}


def stopped_job(cfg, chat: dict) -> str | None:
    """The coding job in this chat that was stopped (or interrupted) and has not carried on yet: its id, or None. Its
    owner's next message in the chat carries it on."""
    latest: dict[str, str] = {}
    for message in (chat or {}).get("messages") or []:
        rid = str(message.get("receipt") or "")
        if rid and message.get("role") == "assistant" and message.get("status") and not message.get("fast"):
            latest[rid] = str(message["status"])
    vault = Vault(cfg.vault)
    for rid, status in reversed(list(latest.items())):
        if status != "paused" or not ID.fullmatch(rid):
            continue
        fm, _ = parse_frontmatter(vault.read(f"Jobs/{rid}.md") or "")
        if fm.get("status") == "paused" and fm.get("kind", "job") == "job":
            return rid
    return None


def carry_on(cfg, rid: str, text: str = "", by: str = "owner") -> dict:
    """Carry a stopped, interrupted or failed job on: the same job, in its own copy of the project, with the same agent
    conversation, from where it stopped. text: what its owner said since, which the job takes in as it carries on."""
    from jcc.redact import redact
    from jcc.resilience import child_alive
    if not ID.fullmatch(str(rid or "")):
        raise ValueError("Invalid job.")
    words = redact(str(text or "").strip())[:4000]
    vault, work = Vault(cfg.vault), cfg.jobs_root / rid
    if not vault.read(f"Jobs/{rid}.md"):
        raise ValueError("Job not found.")
    work.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(work / "job.lock")
    if not lock.acquire():
        raise ValueError("The job is still stopping. Try again in a moment.")
    try:
        fm, body = parse_frontmatter(vault.read(f"Jobs/{rid}.md") or "")
        if fm.get("status") not in ("paused", "failed"):
            raise ValueError("This job is not stopped." if fm.get("status") != "queued" else "This job is already carrying on.")
        if child_alive(work):
            raise ValueError("The job is still stopping. Try again in a moment.")
        if words:
            atomic_write(work / NEXT, json.dumps({"text": words, "by": "jarvis" if by == "jarvis" else "owner", "at": time.time()}))
        atomic_write(work / "control.json", json.dumps({"action": "resume", "at": time.time()}))
        fm.update(status="queued", carried_on_at=time.time())
        vault.write(f"Jobs/{rid}.md", render_note(fm, body))
    finally:
        lock.release()
    receipts.update_status(vault, rid, "queued")
    if fm.get("chat_id"):
        from jcc.chats import Chats
        try:
            Chats(cfg).update(fm["chat_id"], message={"role": "assistant", "receipt": rid, "status": "queued", "resume_requested": True,
                                                       "content": ("The project changed while this job worked: it carries on by itself to combine the two."
                                                                   if by == "jarvis" else "Carrying on from where it stopped" + (", with what you said." if words else "."))})
        except (ValueError, OSError):
            pass
    return {"status": "queued", "carried_on": rid}


def take_next(workdir) -> dict:
    """What its owner said after stopping this job, or what JARVIS found left to do: {"text", "by": "owner"|"jarvis"}, or
    {} (read once: put aside as it is taken)."""
    path = workdir / NEXT
    try:
        saved = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    try:
        path.replace(workdir / ("owner-next-read-%d.json" % int(time.time())))
    except OSError:
        path.unlink(missing_ok=True)
    return {"text": str(saved.get("text") or "")[:4000], "by": "jarvis" if saved.get("by") == "jarvis" else "owner"}


def signal(workdir):
    path = workdir / "control.json"
    try:
        return json.loads(path.read_text("utf-8")).get("action") if path.exists() else None
    except (OSError, ValueError):
        return None


def apply(cfg, rid, action):
    if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{4}", rid) or action not in ("pause", "cancel", "resume"):
        raise ValueError("Invalid job control.")
    vault = Vault(cfg.vault)
    text = vault.read(f"Jobs/{rid}.md")
    if not text:
        raise ValueError("Job not found.")
    fm, body = parse_frontmatter(text)
    state = fm.get("status")
    if state == "needs_approval" and action == "cancel":
        # Waiting for its owner (a change to review, or a question): its owner may end it. Whatever it made is kept.
        fm.update(status="cancelled", asked=False)
        vault.write(f"Jobs/{rid}.md", render_note(fm, body))
        receipts.update_status(vault, rid, "cancelled")
        if fm.get("chat_id"):
            from jcc.chats import Chats
            Chats(cfg).update(fm["chat_id"], message={"role": "assistant", "receipt": rid, "status": "cancelled", "content": "Job cancelled. Existing work is preserved."})
        return {"status": "cancelled"}
    if state in ("done", "cancelled", "needs_approval"):
        raise ValueError("This job cannot be controlled in its current state.")
    work = cfg.jobs_root / rid
    if action == "resume":
        from jcc.resilience import child_alive
        if child_alive(work):raise ValueError('An earlier agent process is still active. Resume is blocked to prevent duplicate edits.')
        if state not in ("paused", "failed"):
            raise ValueError("Pause the job before resuming it.")
        work.mkdir(parents=True, exist_ok=True)
        lock = InstanceLock(work / "job.lock")
        if not lock.acquire():
            raise ValueError("The worker is still stopping. Try again in a moment.")
        try:
            atomic_write(work / "control.json", json.dumps({"action": "resume", "at": time.time()}))
            fm["status"] = "queued"
        finally:
            lock.release()
    else:
        work.mkdir(parents=True, exist_ok=True)
        atomic_write(work / "control.json", json.dumps({"action": action, "at": time.time()}))
        if state == "running":
            return {"status": state, "requested": action}
        fm["status"] = "paused" if action == "pause" else "cancelled"
    vault.write(f"Jobs/{rid}.md", render_note(fm, body))
    receipts.update_status(vault, rid, fm["status"])
    if fm.get("chat_id"):
        from jcc.chats import Chats
        Chats(cfg).update(fm["chat_id"], message={"role": "assistant", "receipt": rid, "status": fm["status"],
            "content": "Job " + fm["status"] + ". Existing work is preserved.", "resume_requested": action == "resume"})
    return {"status": fm["status"]}
