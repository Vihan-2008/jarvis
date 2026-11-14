"""Managed projects and their human-readable Obsidian memory."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from jcc.config import Config, _expand, _project
from jcc.lock import InstanceLock
from jcc.projects import GIT_ID, git
from jcc.vault import Vault, atomic_write, render_note

KEY = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def refresh(cfg: Config) -> None:
    from jcc.vault import read_json
    for key, value in read_json(cfg.state_dir / "projects.json", {}).items():
        if KEY.fullmatch(key):
            try:
                cfg.projects[key] = _project(key, value)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue                      # one damaged entry must not hide the other projects


def create(cfg: Config, name: str, kind: str = "python") -> dict:
    name = name.strip()
    key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    if not KEY.fullmatch(key) or len(name) > 100:
        raise ValueError("Use a project name beginning with a letter (up to 100 characters).")
    if kind not in ("python", "web", "node"):
        raise ValueError("Choose Python, website or Node.js.")
    if kind == "node" and not shutil.which("node"):
        raise ValueError("Node.js is not installed. Choose Python or website, or install Node.js first.")
    lock = InstanceLock(cfg.state_dir / "projects.lock")
    if not lock.acquire():
        raise ValueError("Another project is being created. Try again in a moment.")
    try:
        refresh(cfg)
        root = _expand(cfg.raw["paths"].get("projects_root", str(cfg.state_dir / "projects"))).resolve()
        target = (root / key).resolve()
        if target.parent != root or target.exists() or key in cfg.projects:
            raise ValueError("A project with that name already exists.")
        for protected in [cfg.vault, *cfg.all_protected()]:
            if target.is_relative_to(protected.resolve()):
                raise ValueError("Project location overlaps a protected folder.")
        target.mkdir(parents=True)
        files = {"README.md": f"# {name}\n\nCreated in JARVIS. Describe requirements in the linked chat.\n",
                 ".gitignore": "__pycache__/\n.venv/\n.env\n.env.*\nnode_modules/\n",
                 "AGENTS.md": "Keep changes focused. Add meaningful tests for behavior. Never deploy or access secrets.\n"}
        if kind == "python":
            files.update({"src/__init__.py": "", "src/app.py": 'def main():\n    return "Hello from JARVIS"\n',
                          "tests/__init__.py": "", "tests/test_app.py":
                          "import unittest\nfrom src.app import main\n\nclass AppTest(unittest.TestCase):\n"
                          "    def test_main(self):\n        self.assertEqual(main(), 'Hello from JARVIS')\n"})
            checks = [["-m", "unittest", "discover", "-s", "tests", "-t", "."]]
        elif kind == "web":
            files.update({"index.html": '<!doctype html>\n<html lang="en"><meta charset="utf-8">'
                          f'<title>{key}</title><link rel="stylesheet" href="style.css">'
                          '<main><h1>Your new website</h1></main><script src="app.js"></script></html>\n',
                          "style.css": "body{font-family:system-ui;max-width:960px;margin:80px auto;padding:24px}\n",
                          "app.js": '"use strict";\n', "tests/__init__.py": "",
                          "tests/test_site.py": "import unittest\nfrom pathlib import Path\n\n"
                          "class SiteTest(unittest.TestCase):\n    def test_page(self):\n"
                          "        html = Path('index.html').read_text(encoding='utf-8')\n"
                          "        self.assertIn('<title>', html)\n"
                          "        self.assertTrue(Path('style.css').exists())\n"})
            checks = [["-m", "unittest", "discover", "-s", "tests", "-t", "."]]
        else:
            files.update({"package.json": json.dumps({"name": key, "version": "0.1.0", "private": True,
                          "type": "module", "scripts": {"test": "node --test"}}, indent=2) + "\n",
                          "src/app.js": "export const greet = () => 'Hello from JARVIS';\n",
                          "tests/app.test.js": "import {test} from 'node:test';\nimport assert from 'node:assert/strict';\n"
                          "import {greet} from '../src/app.js';\ntest('greeting', () => assert.equal(greet(), 'Hello from JARVIS'));\n"})
            checks = [[shutil.which("node"), "--test"]]
        for rel, body in files.items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, "utf-8")
        git(["init", "-q", "-b", "main"], target)
        git(["add", "-A"], target)
        git([*GIT_ID, "commit", "-q", "-m", "Create project"], target)
        runtime = Path(sys.executable)
        if runtime.name.lower() == "pythonw.exe" and runtime.with_name("python.exe").exists():
            runtime = runtime.with_name("python.exe")
        entry = {"name": name, "path": str(target), "base_branch": "main", "python": str(runtime),
                 "pythonpath": ["."], "checks": checks, "check_mode": "command" if kind == "node" else "python",
                 "keywords": [key], "auto_merge": True,
                 "no_auto_merge": [".env", ".github/", "deploy/", "Dockerfile", "risk_limits"]}
        path = cfg.state_dir / "projects.json"
        registry = json.loads(path.read_text("utf-8")) if path.exists() else {}
        registry[key] = entry
        atomic_write(path, json.dumps(registry, indent=2))
        cfg.projects[key] = _project(key, entry)
        Vault(cfg.vault).write(f"Projects/{key}/Memory.md", render_note(
            {"project": key, "name": name}, f"# {name}\n\n## Requirements and decisions\n\n"
            "Write durable requirements here. JARVIS retrieves this note for project tasks.\n\n"
            f"Source folder: `{target}`\n\nProject type: {kind}\n"))
        return {"key": key, "name": name, "path": str(target), "kind": kind}
    finally:
        lock.release()


def memory(cfg: Config, project: str | None, query: str = "", source_manifest=None) -> str:
    vault = Vault(cfg.vault)
    from jcc.memory_conflicts import context
    blocks = context(cfg,project)
    if project and project in cfg.projects:
        note = vault.note_for_ai(f"Projects/{project}/Memory")
        if note:
            blocks.append(f"Source: [[Projects/{project}/Memory]]\n" + ('Superseded source; check [['+str(note.frontmatter['superseded_by'])+']].\n' if note.frontmatter.get('superseded_by') else '')+note.body[:1800])
    # Explicit wikilinks are opt-in retrieval. Private notes are refused by note_for_ai.
    for name in re.findall(r"\[\[([^\]|#]+)", query)[:3]:
        note = vault.note_for_ai(name)
        if note:
            blocks.append(f"Source: [[{note.rel.removesuffix('.md')}]]\n{note.body[:1400]}")
    if project and project in cfg.projects:
        summary=vault.note_for_ai(f'Projects/{project}/Recent work')
        if summary:blocks.append(f'Source: [[Projects/{project}/Recent work]]\n'+summary.body[:1000])
    from jcc.memory_search import search
    for rel, passage in search(cfg, query, project):
        if not any(f"[[{rel.removesuffix('.md')}]]" in b for b in blocks):
            blocks.append(f"Source: [[{rel.removesuffix('.md')}]]\n{passage}")
    from jcc.efficiency import settings
    if source_manifest is not None:
        offset=0
        for block in blocks:
            match=re.match(r'^Source: \[\[([^\]]+)\]\]',block)
            if match:source_manifest.append({'name':match[1],'offset':offset,'end':offset+len(block),'reason':'Owner-selected decision.' if '\nOwner-selected decision:' in block else 'Project memory or relevant local retrieval.'})
            offset+=len(block)+2
    return "\n\n".join(blocks)[:settings(cfg)["context_chars"]]
