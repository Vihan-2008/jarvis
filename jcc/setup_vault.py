"""Create the vault structure and starter notes. Never overwrites an existing note
(except System/Router Rules.md, which is a generated read-only mirror)."""

from __future__ import annotations

from jcc.config import ROOT, Config
from jcc.engine import Engine
from jcc.vault import FOLDERS, Vault

JCC = str(ROOT / "jcc.cmd")

INBOX = """# Inbox

Type one request per line as an unchecked box. The watcher picks it up within a few seconds,
ticks it, and links the receipt.

Examples: `- [ ] what are my priorities` · `- [ ] summarize [[Some Note]]` ·
`- [ ] /job build a flashcard app` · `- [ ] /status`

## Requests

- [ ] help
"""

DASHBOARD = """# Command Center

**New request:** add a line to [[Inbox]] like `- [ ] your request`, or in the Terminal plugin run
`{jcc} ask "your request"`. Type `help` for commands. Cost is always 0 (free tiers + your plans).

## Needs your approval
```dataview
TABLE WITHOUT ID file.link AS Job, task AS Task, blocked_by AS "Blocked by"
FROM "Jobs"
WHERE status = "needs_approval"
SORT file.name DESC
```

## Running tier 3 jobs
```dataview
TABLE WITHOUT ID file.link AS Job, task AS Task, tool AS Tool, workdir AS Folder
FROM "Jobs"
WHERE status = "running" OR status = "queued"
SORT file.name DESC
```

## Today by tier
```dataview
TABLE WITHOUT ID tier AS Tier, length(rows) AS Requests, sum(rows.tokens) AS Tokens
FROM "Requests"
WHERE startswith(id, dateformat(date(today), "yyyyMMdd"))
GROUP BY tier
SORT tier ASC
```

## Recent requests
```dataview
TABLE WITHOUT ID link(file.link, request) AS Request, tier AS Tier, router_method AS Router, confidence AS Conf, status AS Status, model AS Model, duration_ms AS ms
FROM "Requests"
SORT id DESC
LIMIT 25
```

## Failures and queued
```dataview
TABLE WITHOUT ID link(file.link, request) AS Request, tier AS Tier, status AS Status, reason AS Reason
FROM "Requests"
WHERE status = "failed" OR status = "queued"
SORT id DESC
LIMIT 15
```

## Free-tier usage today
![[System/Usage]]

## Errors and fallbacks
![[System/Errors]]
"""

PRIORITIES = """# Priorities

Tier 1 answers "what are my priorities" from this note (no AI).

1.
"""

TASKS = """# Tasks

Tier 1 answers "what's on today" from open tasks here, from today's `Daily/YYYY-MM-DD` note,
and from any task tagged `#today` or containing today's date.

- [ ]
"""

PRIVATE = """---
private: true
---
# Private

Anything in this folder is **never sent to any AI model** (enforced in code and tested).
Tier 1 can still find these notes locally on your laptop.
"""

GUIDE = """# Setup guide

## 1. Keys (free, stored in Windows Credential Manager, never in this vault)
Open a terminal (or the Terminal plugin) and run each line; paste the key when asked:

```
{jcc} keys set gemini
{jcc} keys set groq
{jcc} keys set bot
{jcc} keys status
{jcc} test-providers
```

- **gemini**: free key from https://aistudio.google.com/apikey (sign in with your Google account,
  "Create API key"). Do not enable billing. Free-tier prompts may be used by Google to improve its
  products, so personal requests stay in tier 1 and `Private/` is never sent.
- **groq**: a **new, separate** free key from https://console.groq.com/keys — not the trading bot's.
- **bot**: your trading dashboard password (read-only status in tier 1).

## 2. Community plugins (Settings → Community plugins)
1. Click **Turn on community plugins** (leaves Restricted mode).
2. **Browse** → search **Dataview** → Install → Enable. (Powers [[Dashboard]].)
3. **Browse** → search **Terminal** (by polyipseity) → Install → Enable. Then Command palette
   (Ctrl+P) → "Terminal: Open terminal" → choose PowerShell, and run `{jcc} ask "..."`.
4. **Browse** → search **Agent Client** (by RAIT-09) → Install → Enable. To use Claude Code inside
   Obsidian follow https://rait-09.github.io/obsidian-agent-client/agent-setup/claude-code.html
   (Codex and Gemini CLI have their own pages there; they need installing first).
5. Optional: Settings → Core plugins → **Bases** for table views without Dataview.

## 3. Start the watcher
- One-off: run `{jcc} watch` in a terminal and leave it open.
- At every login (optional): run `powershell -ExecutionPolicy Bypass -File "{root}\\scripts\\install-autostart.ps1"`.
  It only adds a hidden start-up entry for the watcher; remove it from the Startup folder any time.

## How it works
- Requests: [[Inbox]] → receipt in `Requests/YYYY/MM/`. Rules: [[System/Router Rules]].
- Tier 3 jobs run in `%LOCALAPPDATA%\\JarvisCommand\\jobs\\<id>` and never deploy, push, delete,
  use keys or touch your real project folders. If needed, they stop and appear under "Needs your approval".
"""

FOLDER_NOTES = {
    "Reports": "Tier 3 job results.",
    "Research": "Tier 3 research reports.",
    "Conversations": "Saved conversations.",
    "Jobs": "One note per tier 3 job: status, work folder and log.",
    "Requests": "Receipts for every request, by year and month.",
}


def setup(cfg: Config) -> list[str]:
    v = Vault(cfg.vault)
    v.ensure_structure()
    log = []

    def create(rel: str, text: str) -> None:
        p = v.path(rel)
        if p.exists():
            log.append(f"kept     {rel} (already exists)")
            return
        v.write(rel, text)
        log.append(f"created  {rel}")

    create("Inbox.md", INBOX)
    create("Dashboard.md", DASHBOARD.format(jcc=JCC))
    create("Priorities.md", PRIORITIES)
    create("Tasks.md", TASKS)
    create("Private/README.md", PRIVATE)
    create("System/Setup Guide.md", GUIDE.format(jcc=JCC, root=str(ROOT)))
    for folder, desc in FOLDER_NOTES.items():
        create(f"{folder}/_About {folder}.md", f"# {folder}\n\n{desc}\n")
    e = Engine(cfg)
    try:
        e.write_rules_note()
        log.append("updated  System/Router Rules.md (generated)")
        if not v.path("System/Usage.md").exists():
            e.write_usage_note()
            log.append("created  System/Usage.md")
        if not v.path("System/Errors.md").exists():
            v.write("System/Errors.md", "# Errors and fallbacks\n\n")
            log.append("created  System/Errors.md")
    finally:
        e.close()
    return log
