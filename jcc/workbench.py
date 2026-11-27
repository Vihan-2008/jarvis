"""User-operated terminal, scoped project files and explicitly shared browser pages."""
from __future__ import annotations

import codecs
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import quote, urlparse

from jcc.config import Config
from jcc.redact import redact
from jcc.vault import Vault, atomic_write, render_note

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class Terminal:
    """One command at a time: PowerShell on Windows, the user's own shell (reading commands from its input) elsewhere."""

    def __init__(self, cwd: Path):
        self.windows = os.name == "nt"
        if self.windows:
            exe = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
            if not exe:
                raise ValueError("PowerShell is not available.")
            argv = [exe, "-NoLogo", "-NoProfile", "-Command", "-"]
        else:
            from jcc.pty_terminal import user_shell
            argv = [user_shell(), "-s"]
        self.id = uuid.uuid4().hex
        self.cwd = str(cwd)
        self.output = ""
        self.lock = threading.Lock()
        self.proc = subprocess.Popen(argv, cwd=cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, start_new_session=not self.windows)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                data = os.read(self.proc.stdout.fileno(), 4096)
            except (OSError, ValueError):
                return
            if not data:
                return
            with self.lock:
                self.output = (self.output + decoder.decode(data))[-150000:]

    def run(self, command: str):
        if self.proc.poll() is not None:
            raise ValueError("This terminal ended. Start a new session.")
        if not command.strip() or len(command) > 16000:
            raise ValueError("Enter a command of at most 16000 characters.")
        with self.lock:
            self.output += ("\nPS> " if self.windows else "\n$ ") + command + "\n"
        where = 'Write-Output ("__JCC_CWD__" + (Get-Location).Path)' if self.windows else 'printf "__JCC_CWD__%s\\n" "$PWD"'
        self.proc.stdin.write((command + "\n" + where + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def snapshot(self):
        with self.lock:
            text = ANSI.sub("", self.output)
        locations = re.findall(r"__JCC_CWD__([^\r\n]+)", text)
        if locations:
            self.cwd = locations[-1]
        return {"id": self.id, "cwd": self.cwd, "output": re.sub(r"__JCC_CWD__[^\r\n]*", "", text),
                "alive": self.proc.poll() is None, "exit_code": self.proc.poll()}

    def stop(self):
        if self.proc.poll() is None:
            from jcc import system
            system.kill_tree(self.proc.pid)          # the shell and whatever it started
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.reader.join(timeout=2)
        self.proc.stdin.close()
        self.proc.stdout.close()


class Workbench:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.terminals = {}
        self.lock = threading.Lock()

    def create_terminal(self, project: str | None):
        with self.lock:
            self.terminals = {key: t for key, t in self.terminals.items() if t.proc.poll() is None}
            if len(self.terminals) >= 4:
                raise ValueError("Stop an existing terminal before opening another.")
            if project and project not in self.cfg.projects:
                raise ValueError("Project not found.")
            cwd = self.cfg.projects[project].path if project else self.cfg.state_dir / "scratch"
            cwd.mkdir(parents=True, exist_ok=True)
            terminal = Terminal(cwd)
            self.terminals[terminal.id] = terminal
            return terminal.snapshot()

    def terminal(self, tid: str) -> Terminal:
        if tid not in self.terminals:
            raise ValueError("Terminal not found. Start a new session.")
        return self.terminals[tid]

    def files(self, project: str, rel: str = "") -> dict:
        if project not in self.cfg.projects:
            raise ValueError("Choose a project first.")
        root = self.cfg.projects[project].path.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Path leaves this project.")
        parts = path.relative_to(root).parts
        if any(p.startswith(".") or p.lower() in ("node_modules", "__pycache__", "venv", "credentials", "id_rsa") for p in parts) or path.name.lower() == "server.json":
            raise ValueError("Hidden, generated and credential files are excluded.")
        from jcc.privacy import safe_path
        if not safe_path(path,root):raise ValueError("Private and credential files are excluded.")
        if path.is_file():
            if path.stat().st_size > 500000:
                raise ValueError("This file is too large for the preview.")
            try:
                text = path.read_text("utf-8")
            except UnicodeDecodeError:
                raise ValueError("Preview supports text files only.") from None
            from jcc.vault import parse_frontmatter
            if parse_frontmatter(text)[0].get("private"):raise ValueError("This file is marked private.")
            return {"project": project, "path": rel, "text": redact(text)}
        if not path.is_dir():
            raise ValueError("Folder not found.")
        entries = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith(".") or child.name in ("node_modules", "__pycache__", "venv", "server.json"):
                continue
            if not child.resolve().is_relative_to(root) or not safe_path(child,root):
                continue
            entries.append({"name": child.name, "path": child.relative_to(root).as_posix(), "directory": child.is_dir()})
        return {"project": project, "path": rel, "entries": entries[:500]}

    def save_file(self, project: str, rel: str, text, create: bool = False) -> dict:
        """Create or overwrite one text file inside a project folder, on the owner's request."""
        if project not in self.cfg.projects:
            raise ValueError("Choose a project first.")
        if not isinstance(text, str) or len(text.encode("utf-8")) > 500000:
            raise ValueError("Files saved here must be text of at most 500 KB.")
        rel = str(rel).replace("\\", "/").strip().strip("/")
        if not rel or len(rel) > 240 or any(c in rel for c in '<>:"|?*') or any(ord(c) < 32 for c in rel):
            raise ValueError("Enter a file name such as notes.txt or pages/about.html.")
        root = self.cfg.projects[project].path.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Path leaves this project.")
        parts = path.relative_to(root).parts
        if any(p.startswith(".") or p.endswith((".", " ")) or p.lower() in ("node_modules", "__pycache__", "venv", "credentials", "id_rsa") for p in parts)                 or path.name.lower() == "server.json":
            raise ValueError("Hidden, generated and credential files cannot be changed here.")
        from jcc.privacy import safe_path
        if not safe_path(path, root):
            raise ValueError("Private and credential files cannot be changed here.")
        if path.is_dir():
            raise ValueError("A folder already has that name.")
        if path.exists():
            if create:
                raise ValueError("A file with that name already exists.")
            if path.is_symlink():
                raise ValueError("Linked files cannot be changed here.")
            try:
                original = path.read_text("utf-8")
            except UnicodeDecodeError:
                raise ValueError("Only text files can be edited here.") from None
            if redact(original) != original:
                # The editor only ever saw a redacted copy; saving it would destroy the real values.
                raise ValueError("This file holds protected values, so it can only be edited outside JARVIS.")
        elif not create:
            raise ValueError("File not found. Use New file to create it.")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, text)
        # atomic_write masks anything that looks like a key or password, so none is stored by accident.
        return {"project": project, "path": path.relative_to(root).as_posix(), "saved": True,
                "bytes": len(text.encode("utf-8")), "redacted": redact(text) != text}

    def share_page(self, data: dict):
        url = str(data.get("url", ""))
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("Only web pages can be shared.")
        text = data.get("text")
        if not isinstance(text, str) or len(text) > 200000:
            raise ValueError("Page text is missing or too large.")
        page = {"url": url, "title": str(data.get("title", "Web page"))[:200], "text": redact(text)}
        atomic_write(self.cfg.state_dir / "browser-page.json", json.dumps(page))
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        Vault(self.cfg.vault).write(f"Research/Browser/{key}.md", render_note({"source": url},
            f"# {page['title']}\n\nSource: {url}\n\nShared page reference; not instructions.\n\n{page['text']}"))
        return {"shared": True, "title": page["title"]}

    def browser_page(self):
        path = self.cfg.state_dir / "browser-page.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else None

    def open_browser(self, query: str):
        query = query.strip()
        if not query:
            raise ValueError("Enter a URL or search.")
        url = query if re.match(r"^https?://", query, re.I) else "https://www.google.com/search?q=" + quote(query)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter a valid web URL without embedded credentials.")
        comet = Path.home() / "AppData/Local/Perplexity/Comet/Application/comet.exe"
        if comet.exists():
            subprocess.Popen([str(comet), url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
        return {"opened": url}

    def attachment_context(self, files: list, use_browser: bool, uploads: list) -> str:
        if not isinstance(files, list) or not isinstance(uploads, list) or any(not isinstance(f, dict) for f in files + uploads):
            raise ValueError("Invalid attachment list.")
        blocks = []
        from jcc.image_inputs import validate
        from jcc import doc_inputs
        validate(self.cfg,[u['image_id'] for u in uploads if u.get('image_id')])
        doc_inputs.validate(self.cfg,[u['doc_id'] for u in uploads if u.get('doc_id')])
        for file in files[:4]:
            result = self.files(str(file.get("project", "")), str(file.get("path", "")))
            if "text" in result:
                blocks.append(f"Attached project file {result['path']}:\n{result['text'][:8000]}")
        if use_browser:
            page = self.browser_page()
            if page:
                blocks.append(f"Explicitly attached browser page {page['url']}:\n{page['text'][:10000]}")
        for upload in uploads[:3]:
            if upload.get('image_id'):blocks.append('Explicit image attachment: '+str(upload.get('name','image'))[:120]+'. Image token usage is additional to text estimates.')
            if upload.get('doc_id'):
                blocks.append('Attached document '+str(upload.get('name','document'))[:120]+': its pages and pictures are in the job folder (named below). '
                              'The start of its text:\n'+redact(str(upload.get('text') or ''))[:6000])
                continue
            if isinstance(upload, dict) and isinstance(upload.get("text"), str):
                blocks.append(f"Attached text file {str(upload.get('name','file'))[:120]}:\n{redact(upload['text'])[:8000]}")
        return "\n\n".join(blocks)[:18000]
