"""Private vault backup. This controller never pushes a coding project's repository."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from jcc.config import Config
from jcc.lock import InstanceLock
from jcc.vault import Vault, atomic_write


def git(cfg, *args, check=True):
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
    result = subprocess.run(["git", "-C", str(cfg.vault), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", env=env, timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check and result.returncode:
        raise ValueError(result.stderr.strip()[:300] or "Vault Git operation failed.")
    return result.stdout.strip()


def setup(cfg: Config):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    # Whose GitHub account: the name in the settings ([vault_git] username), if there is one; otherwise whichever
    # account this PC's own key store holds for github.com.
    named = str((cfg.raw.get("vault_git") or {}).get("username") or "").strip() if isinstance(cfg.raw.get("vault_git"), dict) else ""
    asked = "protocol=https\nhost=github.com\n" + ("username=" + named + "\n" if re.fullmatch(r"[A-Za-z0-9-]{1,39}", named) else "") + "\n"
    result = subprocess.run(["git", "credential", "fill"], input=asked,
                            capture_output=True, text=True, env=env, timeout=30)
    if result.returncode:
        raise ValueError("GitHub authentication is required.")
    credential = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = credential.get("password", "")
    def request(method, path, data=None):
        req = urllib.request.Request("https://api.github.com" + path, method=method,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": "JARVIS-Brain"},
            data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    account = request("GET", "/user")
    owner = account["login"]
    name = "jarvis-brain-vault"
    for suffix in ("", time.strftime("-%Y%m%d-%H%M%S")):
        candidate = name + suffix
        try:
            request("GET", f"/repos/{owner}/{candidate}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            name = candidate
            break
    else:
        raise ValueError("Choose a different repository name.")
    if (cfg.vault / ".git").exists() and git(cfg, "remote", "get-url", "origin", check=False):
        raise ValueError("The vault already has a remote; it was not changed.")
    ignore = cfg.vault / ".gitignore"
    old = ignore.read_text("utf-8") if ignore.exists() else ""
    rules = "\n# JARVIS local state and credentials\n.obsidian/workspace*.json\n.obsidian/cache/\n.obsidian/plugins/\n.trash/\n.env\n.env.*\n*.pem\n*.key\n*.p12\n*.pfx\n"
    if "# JARVIS local state" not in old:
        atomic_write(ignore, old.rstrip() + "\n" + rules)
    if not (cfg.vault / ".git").exists():
        git(cfg, "init", "-b", "main")
    git(cfg, "config", "user.name", owner)
    git(cfg, "config", "user.email", f"{account['id']}+{owner}@users.noreply.github.com")
    git(cfg, "config", "core.quotepath", "false")
    plugin = cfg.vault / ".obsidian/plugins/obsidian-git/data.json"
    values = json.loads(plugin.read_text("utf-8")) if plugin.exists() else {}
    values.update({"autoSaveInterval": 10, "autoPushInterval": 10, "differentIntervalCommitAndPush": False,
                   "disablePush": False, "pullBeforePush": True, "autoPullInterval": 0, "autoBackupAfterFileChange": False})
    atomic_write(plugin, json.dumps(values, indent=2))
    repo = request("POST", "/user/repos", {"name": name, "private": True,
                   "description": "Private Obsidian second brain and shared JARVIS memory", "auto_init": False})
    url = repo["clone_url"]
    git(cfg, "remote", "add", "origin", url)
    Vault(cfg.vault).write("System/Git Backup.md", f"# Private vault backup\n\nRepository: [{owner}/{name}]({repo['html_url']})\n\n"
        "Obsidian Git is configured to commit and sync every 10 minutes. JARVIS also backs up while Obsidian is closed.\n\n"
        "Plugin binaries, local workspace state and credential files are ignored. Notes remain in the private repository.\n")
    git(cfg, "add", "-A")
    if git(cfg, "status", "--porcelain"):
        git(cfg, "commit", "-m", "Back up Obsidian second brain")
    git(cfg, "push", "-u", "origin", "HEAD")
    saved = {"url": repo["html_url"], "remote": url, "private": True, "interval_minutes": 10}
    atomic_write(cfg.state_dir / "github.json", json.dumps(saved))
    atomic_write(cfg.state_dir / "github-status.json", json.dumps({"at": time.time(), "status": "synced", **saved}))
    return saved


def sync(cfg: Config):
    config = cfg.state_dir / "github.json"
    if not config.exists():
        return
    status_path = cfg.state_dir / "github-status.json"
    status = json.loads(status_path.read_text("utf-8")) if status_path.exists() else {}
    if time.time() - status.get("at", 0) < 600:
        return
    lock = InstanceLock(cfg.state_dir / "vault-git.lock")
    if not lock.acquire():
        return
    try:
        expected = json.loads(config.read_text("utf-8"))
        if git(cfg, "remote", "get-url", "origin") != expected["remote"]:
            raise ValueError("Vault remote changed; automatic push paused.")
        if (cfg.vault / ".git/index.lock").exists():
            return
        git(cfg, "add", "-A")
        if git(cfg, "status", "--porcelain"):
            git(cfg, "commit", "-m", "Vault backup " + time.strftime("%Y-%m-%d %H:%M"))
        if int(git(cfg, "rev-list", "--count", "@{upstream}..HEAD") or "0"):
            git(cfg, "push")
        value = {"at": time.time(), "status": "synced", **expected}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        value = {"at": time.time(), "status": "error", "error": str(e)[:300]}
    finally:
        lock.release()
    atomic_write(status_path, json.dumps(value))
