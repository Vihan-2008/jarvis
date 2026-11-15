"""Configuration: config/default.toml, overridden by config/local.toml and JCC_* env vars."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("small", "medium", "large")


def data_home() -> Path:
    """Where an app keeps its own data on this system: AppData\\Local on Windows, ~/Library/Application Support on a
    Mac, and $XDG_DATA_HOME (or ~/.local/share) elsewhere."""
    import sys
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _expand(p: str) -> Path:
    """A path from the settings, with ~ and variables filled in. %LOCALAPPDATA% means the app's data folder on every
    system (see data_home), and either kind of slash is taken."""
    text = str(p)
    if os.name != "nt":
        text = text.replace("%LOCALAPPDATA%", str(data_home())).replace("\\", "/")
    return Path(os.path.expandvars(text)).expanduser()


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@dataclass(frozen=True)
class Cap:
    requests: int
    tokens: int


@dataclass(frozen=True)
class AgentCfg:
    name: str
    enabled: bool
    command: list[str]           # executable (+ fixed args), e.g. ["claude"] or a test stub
    models: dict[str, str]


@dataclass(frozen=True)
class ProjectCfg:
    key: str
    name: str
    path: Path
    base_branch: str
    python: Path                 # absolute path to the project's venv python
    pythonpath: list[str]
    checks: list[list[str]]      # argv tails run with `python` inside the branch copy
    keywords: list[str]
    auto_merge: bool
    no_auto_merge: list[str]
    check_mode: str = "python"


@dataclass
class Config:
    vault: Path
    state_dir: Path
    jobs_root: Path
    protected: list[Path]
    classifier: str
    rule_confidence: float
    model_confidence: float
    tier3_min_confidence: float
    models: dict[str, str]
    caps: dict[str, Cap]
    tier3_max_running: int
    tier3_timeout_minutes: int
    cooldown_hours: float
    levels: dict[str, list[str]]
    agents: dict[str, AgentCfg]
    projects: dict[str, ProjectCfg]
    bot_url: str
    bot_user: str
    raw: dict[str, Any] = field(default_factory=dict)

    def all_protected(self) -> list[Path]:
        """Never-touch folders plus every project's MAIN checkout (agents use branch copies)."""
        return [*self.protected, *(p.path for p in self.projects.values())]


def _agent(name: str, d: dict[str, Any]) -> AgentCfg:
    cmd = d.get("command", name)
    return AgentCfg(name=name, enabled=bool(d.get("enabled", True)),
                    command=[cmd] if isinstance(cmd, str) else [str(c) for c in cmd],
                    models={lvl: str(d.get("models", {}).get(lvl, "")) for lvl in LEVELS})


WINDOWS_VENV_PYTHON = r".venv\Scripts\python.exe"
POSIX_VENV_PYTHON = ".venv/bin/python"


def venv_python(text: str | None = None, windows: bool | None = None) -> str:
    """A project's Python as this system names it. A virtual environment keeps it in Scripts\\python.exe on Windows and
    in bin/python elsewhere, so a setting written either way (or none) means the one that exists on this system."""
    windows = os.name == "nt" if windows is None else windows
    text = str(text) if text else (WINDOWS_VENV_PYTHON if windows else POSIX_VENV_PYTHON)
    plain = text.replace("\\", "/")
    if plain.startswith("/") or (len(plain) > 1 and plain[1] == ":"):
        return text                     # a full path names one particular Python: it is used as it is written
    if windows and plain.endswith("/bin/python"):
        return plain[: -len("bin/python")].replace("/", "\\") + r"Scripts\python.exe"
    if not windows and plain.lower().endswith("/scripts/python.exe"):
        return plain[: -len("Scripts/python.exe")] + "bin/python"
    return text if windows else plain


def _project(key: str, d: dict[str, Any]) -> ProjectCfg:
    path = _expand(d["path"])
    py = Path(venv_python(d.get("python")))
    return ProjectCfg(
        key=key, name=d.get("name", key), path=path, base_branch=d.get("base_branch", "main"),
        python=py if py.is_absolute() else path / py,
        pythonpath=list(d.get("pythonpath", ["src", "."])),
        checks=[list(map(str, c)) for c in d.get("checks", [])],
        keywords=[k.lower() for k in d.get("keywords", [])],
        auto_merge=bool(d.get("auto_merge", False)),
        no_auto_merge=list(d.get("no_auto_merge", [])),
        check_mode=d.get("check_mode", "python"),
    )


def load(overrides: dict[str, Any] | None = None) -> Config:
    data: dict[str, Any] = tomllib.loads((ROOT / "config" / "default.toml").read_text("utf-8"))
    usual = dict(data["paths"])
    local = ROOT / "config" / "local.toml"
    if local.exists() and not os.environ.get("JCC_NO_LOCAL_CONFIG"):       # (tests never read one PC's own settings)
        data = _merge(data, tomllib.loads(local.read_text("utf-8")))
    if overrides:
        data = _merge(data, overrides)
    p, r, t, b = data["paths"], data["router"], data["tier3"], data.get("bot") or {}
    if p["state_dir"] != usual["state_dir"]:
        # JARVIS's data was moved (a second copy, kept apart from the first): its jobs and projects go with it, unless
        # they were moved too. (A development copy once ran its jobs in the folder of the JARVIS its owner uses.)
        for key, folder in (("jobs_root", "jobs"), ("projects_root", "projects")):
            if p.get(key) == usual.get(key):
                p[key] = str(Path(p["state_dir"]) / folder)
    vault = os.environ.get("JCC_VAULT") or p["vault"]
    state = os.environ.get("JCC_STATE_DIR") or p["state_dir"]
    jobs = os.environ.get("JCC_JOBS_ROOT") or p["jobs_root"]
    if os.environ.get("JCC_PROJECTS_ROOT") and "projects_root" not in ((overrides or {}).get("paths") or {}):
        p["projects_root"] = os.environ["JCC_PROJECTS_ROOT"]      # a test or a preview keeps the projects it creates with its other files
    registry = _expand(state) / "projects.json"
    if registry.exists():
        from jcc.vault import read_json
        added = {}
        for key, value in read_json(registry, {}).items():
            try:
                _project(key, value)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue                      # a damaged list or entry must not stop JARVIS from starting
            added[key] = value
        data["projects"] = {**data.get("projects", {}), **added}
    routing = _expand(state) / "routing.json"
    import copy
    data["routing_defaults"] = copy.deepcopy({"levels": t.get("levels", {}), "agents": data.get("agents", {})})
    if routing.exists():
        import re
        from jcc.vault import read_json
        selected = {level: choice for level, choice in read_json(routing, {}).items() if isinstance(choice, dict)}
        data["routing_choices"] = selected
        for level, choice in selected.items():
            provider, _, model = str(choice.get("model", "")).partition(":")
            if level not in LEVELS or provider not in data.get("agents", {}) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", model):
                continue
            order = data["tier3"].setdefault("levels", {}).get(level, ["claude", "codex"])
            data["tier3"]["levels"][level] = [provider] + [p for p in order if p != provider]
            data["agents"][provider].setdefault("models", {})[level] = model
    return Config(
        vault=_expand(vault),
        state_dir=_expand(state),
        jobs_root=_expand(jobs),
        protected=[_expand(x) for x in p.get("protected", [])],
        classifier=r["classifier"],
        rule_confidence=float(r["rule_confidence"]),
        model_confidence=float(r["model_confidence"]),
        tier3_min_confidence=float(r["tier3_min_confidence"]),
        models=dict(data["models"]),
        caps={k: Cap(int(v["requests"]), int(v["tokens"])) for k, v in data["caps"].items()},
        tier3_max_running=int(t["max_running"]),
        tier3_timeout_minutes=int(t["timeout_minutes"]),
        cooldown_hours=float(t.get("cooldown_hours", 5)),
        levels={lvl: list(t.get("levels", {}).get(lvl, ["claude"])) for lvl in LEVELS},
        agents={k: _agent(k, v) for k, v in data.get("agents", {}).items()},
        projects={k: _project(k, v) for k, v in data.get("projects", {}).items()},
        bot_url=str(b.get("url") or ""),
        bot_user=str(b.get("user") or ""),
        raw=data,
    )
