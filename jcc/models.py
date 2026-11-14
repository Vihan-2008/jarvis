"""Model picker backed by local provider catalogs, not an invented universal model list."""
import os
import re
from pathlib import Path

from jcc.vault import read_json


FULL = ["low", "medium", "high", "xhigh", "max"]       # every level Claude Code's --effort takes
STRONGEST = ("fable", "opus")                          # Claude's strongest models, the strongest first


def catalog(cfg) -> list[dict]:
    claude = [{"id": "claude:" + name, "provider": "claude", "model": name, "label": "Claude " + name.title(),
               "efforts": [] if name == "haiku" else list(FULL)}
              for name in ("haiku", "sonnet", "opus")]
    # Both lists are other programs' files as much as ours: they can be empty or half-written at any moment.
    listed = read_json(cfg.state_dir / "quota-claude.json", {}).get("models", [])
    for model in listed if isinstance(listed, list) else []:
        name = model.get("value") if isinstance(model, dict) else None
        shown = model.get("displayName") if isinstance(model, dict) else None
        for known in claude:                                 # the three that are always there are called what Claude Code calls them ("Opus 5.5")
            if known["model"] == name and isinstance(shown, str) and 0 < len(shown) <= 60:
                known["label"] = shown
        if isinstance(name, str) and name != "default" and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name) and not any(m["model"] == name for m in claude):
            efforts = model.get("efforts")
            claude.append({"id": "claude:" + name, "provider": "claude", "model": name, "label": str(model.get("displayName") or name),
                           "efforts": efforts if isinstance(efforts, list) and efforts else list(FULL) if name in STRONGEST else ["low", "medium", "high"]})
    listed = read_json(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json", {}).get("models", [])
    codex = []
    for model in listed if isinstance(listed, list) else []:
        if not isinstance(model, dict) or model.get("visibility") != "list" or not isinstance(model.get("slug"), str):
            continue
        levels = model.get("supported_reasoning_levels")
        codex.append({"id": "codex:" + model["slug"], "provider": "codex", "model": model["slug"],
                      "label": str(model.get("display_name") or model["slug"]),
                      "efforts": [r["effort"] for r in levels if isinstance(r, dict) and isinstance(r.get("effort"), str)] if isinstance(levels, list) else []})
    if not codex:
        agent = cfg.agents.get("codex")
        codex = [{"id": "codex:" + name, "provider": "codex", "model": name, "label": name,
                  "efforts": ["low", "medium", "high"]} for name in dict.fromkeys(agent.models.values() if agent else []) if name]
    return claude + codex + _grok(cfg)


def _grok(cfg) -> list[dict]:
    """Grok's models, from the list its own command-line tool keeps on this PC. Only when Grok is switched on."""
    agent = cfg.agents.get("grok")
    if not agent or not agent.enabled:
        return []
    listed = read_json(Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))) / "models_cache.json", {}).get("models", {})
    found = []
    for slug, entry in (listed.items() if isinstance(listed, dict) else []):
        info = entry.get("info") if isinstance(entry, dict) and isinstance(entry.get("info"), dict) else {}
        if isinstance(slug, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", slug):
            found.append({"id": "grok:" + slug, "provider": "grok", "model": slug, "label": str(info.get("name") or slug)[:60], "efforts": ["low", "medium", "high"]})
    return found


def strongest(cfg) -> str | None:
    """The strongest Claude model this PC's Claude Code offers: what Ultracode works with when no model is named."""
    names = {m["model"] for m in catalog(cfg) if m["provider"] == "claude"}
    return next((name for name in STRONGEST if name in names), None)


def validate(cfg, model: str = "auto", effort: str = "auto") -> dict | None:
    if effort not in ("auto", "low", "medium", "high", "xhigh", "max", "ultra"):
        raise ValueError("Unsupported reasoning effort.")
    if not model or model == "auto":
        return None
    selected = next((m for m in catalog(cfg) if m["id"] == model), None)
    if not selected:
        raise ValueError("That model is not in the installed provider catalog.")
    if effort not in ("auto", "ultra") and effort not in selected["efforts"]:      # ultra goes with any model: as hard as that one can think
        raise ValueError("That effort level is not supported by this model.")
    return selected
