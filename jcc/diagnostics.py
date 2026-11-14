"""Independent source health, including stale or unsuccessful capture attempts."""
import json
import time
from jcc.vault import atomic_write


def read(cfg, name):
    path = cfg.state_dir / f"{name}-status.json"
    try:
        return json.loads(path.read_text("utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return {"status": "error", "error": "Status file could not be read."}


def probe(cfg, data):
    source = data.get("source")
    if source not in ("ChatGPT", "Claude"):
        raise ValueError("Unknown capture source.")
    value = {"at": time.time(), "source": source, "messages": max(0, min(100000, int(data.get("messages", 0)))),
             "saved": bool(data.get("saved")), "error": str(data.get("error", ""))[:160],
             "pending": max(0, min(20, int(data.get("pending", 0)))), "version": str(data.get("version", ""))[:20]}
    checked = float(data.get("at", 0)) / 1000
    structure=data.get('structure',{})
    if isinstance(structure,dict):
        value['structure']={k:max(0,min(100000,int(structure.get(k,0)))) for k in ('roots','candidates','recognized')}
    value["page_checked_at"] = checked if 0 < checked <= time.time() else None
    atomic_write(cfg.state_dir / f"probe-{source.lower()}-status.json", json.dumps(value))
    return {"ok": True}


def snapshot(cfg):
    result = {}
    legacy = read(cfg, "capture")
    for source in ("ChatGPT", "Claude"):
        saved = read(cfg, "capture-" + source.lower()) or (legacy if legacy and legacy.get("source") == source else None)
        observed = read(cfg, "probe-" + source.lower())
        state = "no capture received" if not saved else "last capture saved"
        if observed and observed.get("error"):
            state = observed["error"]
        elif observed and not observed.get("saved"):
            state = "open a saved conversation"
        elif observed and not observed.get("messages"):
            state = "page detected; no messages found"
        if observed and observed.get("page_checked_at") and time.time() - observed["page_checked_at"] > 120:
            state = "extension reported an older page; refresh a saved conversation"
        if saved and time.time() - saved.get("at", 0) > 3600:
            state += " · no recent capture"
        result[source + " website"] = {"status": state, "last_success": (saved or {}).get("at"), "observed": observed}
    for name, label in (("local-history", "Local coding chats"), ("cloud-memory", "Supabase"), ("github", "GitHub")):
        value = read(cfg, name)
        if name == "local-history" and value:
            value["status"] = "saving locally" if time.time() - value.get("at", 0) < 120 else "worker status is stale"
        result[label] = value or {"status": "not connected"}
    return result
