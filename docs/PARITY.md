# JARVIS compared with T3 Code and Cursor

What two well-known AI coding tools do, feature by feature, and what JARVIS does instead, where it falls short, and how
JARVIS's side was checked. Written 15 Nov 2026.

- **T3 Code** (github.com/pingdotgg/t3code, MIT licence): its user documentation at commit `ea05ea5e2af2`
  (14 Nov 2026), all 49 user docs read. No T3 Code code is used in JARVIS, so no attribution is owed.
- **Cursor**: its official documentation at cursor.com/docs and the changelog, read 15 Nov 2026. Seven pages answered
  "not found" (notebooks, checkpoints, shell, four privacy pages); those rows rely on the pages that did load.

Words used in the JARVIS column: **Has** (JARVIS does this, perhaps differently), **Partly**, **Missing**, **Not wanted**
(left out on purpose: JARVIS is a desktop app for one person on their own computer, with nothing run in a cloud).
"Checked by" names the strongest evidence for JARVIS's side: *real* (a real run with real AI services), *installed*
(the app on its owner's PC), *real Mac* (GitHub's macOS machine, `scripts/mac_live_check.py`), *tests* (the automated
suites), *page* (the window in a hidden browser against a throwaway copy), *code* (present in the code, not checked
for this table).

JARVIS is not an editor. T3 Code and Cursor are where a developer writes code; JARVIS is an assistant you talk to,
which hands coding work to coding agents (Claude Code, Codex, Grok) in a copy of your project, checks it, and merges it.
So the editor rows below are gaps by nature, not oversights.

## T3 Code

| Feature | T3 Code | JARVIS | Gap | Checked by |
|---|---|---|---|---|
| Coding agents | Runs the agents installed on the computer: Claude Code, Codex, Cursor, OpenCode, Kiro, Pi, Grok Build, Antigravity, Muse, fx, any ACP agent; one chosen per thread. | **Partly.** Claude Code, Codex and Grok's CLI; JARVIS picks one by the size of the task, or you choose. | No Cursor, OpenCode, Kiro, Pi, Antigravity or ACP agents. | real |
| Provider instances and accounts | A second instance of a provider with its own account, binary or settings; shared-home Codex accounts. | **Missing.** One account per agent: whichever the CLI is signed in to. | Several accounts per agent. | — |
| Models and defaults | Custom models, renamed models, remembered defaults per new thread. | **Has.** A model list per provider, a choice per chat, and effort levels; the choice is remembered. | Custom model names. | tests |
| Compaction | Auto-compact at a token count; `/compact` in any thread. | **Partly.** A long chat can be compacted on request. | No automatic compaction setting. | code |
| Skills and plugins | Claude skills and plugin skills under `$`. | **Has.** Skill packs, scanned before use (SkillSpector); only the skills that fit a task are given to it. | — | tests |
| Text generators | A chosen model writes titles, commit messages, PR text, branch names. | **Partly.** Chat titles and job commit messages are written for you. | No separate model choice per writing task; no PR text. | code |
| Threads, projects, worktrees | Threads per project; a worktree when the code needs its own branch. | **Has.** Chats, and projects; every coding job works in its own copy of the project and is merged only after the project's checks pass. | — | real |
| Thread without a project | A scratch thread that can be turned into a project. | **Partly.** An ordinary chat needs no project; projects are made on their own. | Turning a chat into a project. | page |
| Sidebar organisation | Pin, reorder, snooze, settle; undo for five seconds. | **Partly.** Chats can be pinned, foldered, tagged, searched and deleted. | Snooze, settle and drag to reorder. | page |
| Usage-limit continuation | Resume at reset, or snooze until the allowance returns. | **Has.** "Waiting for an AI to be available again": JARVIS carries on by itself at the reset time, or now on request; it can also hand over to another AI. | — | tests |
| Subagents view | Delegated work listed under Agents. | **Has.** The Agents panel lists everything working, waiting for you, scheduled or recently done. | — | installed |
| Side chats | `/side` or `/btw` asks about a thread without adding to it; Bring back. | **Missing.** | Side chats. | — |
| Search | Command palette across threads; message search opens the message. | **Partly.** Ctrl+K searches chats. | Search inside messages that jumps to the message. | page |
| Portable handoffs | Switching provider passes a trimmed copy of the conversation. | **Partly.** A job that one agent cannot finish goes to the next agent; project handoff exports exist. | A chat moved from one AI to another with its history. | real |
| Composer | Markdown styling as you type; 120,000 characters; long pastes become files. | **Partly.** A plain message box with Markdown in the replies. | Styling as you type; long pastes as files. | page |
| Attachments | Up to 100 files, images pasted or dragged, HEIC converted. | **Has.** Files and images attached, pasted or dragged; audio and video written out as text. | HEIC conversion. | tests |
| Send while the agent works | A message queues for the next turn or steers the running one. | **Partly.** A running job that asks a question gets your answer; Stop keeps what was finished. | Steering a running turn; queued messages. | real |
| Recall and edit sent prompts | ArrowUp recalls; Edit from here rewinds, optionally reverting files. | **Partly.** "Edit and send again" and "Try again" on any message. | Rewinding files with the chat. | page |
| Prompt stash | Ctrl+S stashes a draft and its attachments. | **Missing.** | Stash. | — |
| Cite and context chips | Quote part of a reply into the composer; terminal, review and file chips. | **Missing.** | Citing; chips. | — |
| Mentions | `#` pull requests, `@` threads and models. | **Missing.** | `@` mentions of chats, files and models. | — |
| Slash commands | `/` commands and `$` skills. | **Partly.** `/` commands in the message box. | `$` skills; `/goal`. | page |
| Suggested next prompt | Predicted next message after a turn. | **Missing** (on purpose for now: each suggestion costs a request). | — | — |
| Voice dictation | Dictate into the draft; local or cloud model; dictionary; cleanup. | **Has**, and more: voice chat, "Hey JARVIS", dictation into any app, a list of names and unusual words, the computer's own sound ignored. | Transcript clean-up step. | real Mac, tests |
| Prompt links | A link opens a draft with a prompt filled in. | **Missing.** | Prompt links. | — |
| Git hosts, PRs, review guides, stacks | Sign in to GitHub and others; clone, commit, push, open and merge PRs; review guides; stacked PRs. | **Partly.** Local git: jobs commit and merge into your branch; a job's change can be reviewed before it is merged and undone after. | Pull requests and every git host feature. | real |
| Turn diffs | A turn's own diff; commits one at a time. | **Has.** Each job's change, shown before and after it is merged. | — | real |
| Terminals | Terminals kept on the server with long scrollback. | **Has.** An interactive terminal panel (PowerShell, zsh or bash) and one-off commands. | — | tests |
| Project scripts and actions | Commands in `t3.json` run from a terminal or on settle. | **Partly.** Each project's checks (its tests) run before a merge. | Named actions with keys. | real |
| Activity log | Tool calls collapse into summaries; Zen hides them. | **Has.** Live progress of each job and each reply, step by step. | A hide-all view. | page |
| Permission modes | Supervised, Auto-accept edits, Auto, Full access. | **Has.** Three ways of asking (only before sending, deleting or paying; also before risky things; before everything); things never done in any mode. | — | installed, tests |
| Remote access, devices, mobile, guest links, outside agents | Relay, pairing, LAN and Tailscale routes, SSH hosts, simulators, phone apps, guest links, MCP access for outside agents. | **Not wanted.** Its owner asked for a desktop app only. | — | — |
| Background service | Runs as a user service. | **Has.** The background helper starts at sign-in (Windows, and on a Mac when chosen at install). | — | real Mac |
| Updates and channels | `t3 update`, channels, update every machine. | **Partly.** New versions are released on GitHub; the installer upgrades in place. | Updating from inside the app. | real Mac |
| Notifications | Phone alerts and live activities. | **Partly.** A desktop alert when a job finishes (Windows); reminders. | Alerts on a Mac when a job finishes. | code |
| Scheduled tasks | A prompt on a schedule, into one thread or a new one. | **Has.** Routines: a request on a schedule, in its own chat. | — | tests, page |
| Webhook automations | A task runs when another service calls its URL. | **Missing.** | Event triggers. | — |
| Settings scope | Per environment, all environments, or per project. | **Partly.** App settings, and per-project rules for jobs. | Per-project settings for everything. | code |
| Appearance | Themes, per-mode themes, custom CSS, LaTeX. | **Partly.** Light, dark or system; mods can restyle the window. | Custom themes; LaTeX. | page |
| Keybindings | Rebind every command. | **Partly.** Fixed shortcuts in the window; the global ones fall back to another key when taken. | Rebinding. | page |
| Managed policy | Admin defaults and locks. | **Not wanted** (one owner). | — | — |
| Worktree clean-up | Remove worktrees by age, merge or deletion. | **Partly.** Old downloads are moved aside after a set number of days. | Clearing old job copies by age or merge. | code |
| Secrets | 1Password references; secret cards in threads. | **Partly.** Keys only in Windows Credential Manager, the macOS Keychain or environment variables; never typed for anyone. | 1Password. | tests |
| Usage page | Tokens, cost and cache per model; subscription windows. | **Has.** Usage by model and agent, allowances, budgets per day, task and project. | Custom prices. | tests |
| Telemetry | Product events sent to T3 Code (can be turned off). | **Has**, differently: JARVIS sends nothing about you anywhere. | — | code |
| Triage | An agent investigates a T3 Code problem and drafts an issue. | **Partly.** Checks, repairs and recovery; a security check of any project. | Drafting an issue about JARVIS itself. | real |
| Screenshots into the draft | Capture the window you work in. | **Has.** A picture of a window or a screen into the chat (Windows and Mac). | — | real Mac |
| Browser and cookies | Preview browser with imported cookies; default browser. | **Partly.** A built-in browser panel that keeps sign-ins (Windows). | Cookie import; the panel on a Mac. | code |
| Visual replies | Self-contained HTML charts and diagrams, sandboxed. | **Has.** Artifacts (pages, apps, sheets, slides, diagrams) with versions, in a sealed preview. | — | page |
| Installers | Desktop app, CLI, brew, winget, scoop, Nix, apt, AUR. | **Partly.** Windows Setup.exe and zip; Mac .dmg and zip; from source. | Package managers. | real Mac |

## Cursor

| Feature | Cursor | JARVIS | Gap | Checked by |
|---|---|---|---|---|
| Agent with codebase tools | Searches, edits many files, runs commands, fixes errors. | **Has**, through Claude Code, Codex or Grok, in a copy of the project, merged after checks. | — | real |
| @-mentions (files, folders, terminals, chats, diffs, browser) | Attach exactly what the AI should see. | **Missing** in the message box (files can be attached). | `@` mentions. | — |
| Images in chat | Paste screenshots. | **Has.** | — | tests |
| Context ring and summaries | Shows how full the context is; long chats summarised. | **Partly.** A context inspector; compaction on request. | A live ring. | code |
| Rules (project, user, team, AGENTS.md, globs) | Standing guidance for the agent. | **Partly.** Jobs are told to follow the project's CLAUDE.md or AGENTS.md; "About you" for the assistant. | Glob-scoped rules; team rules (not wanted). | code |
| Skills and custom modes | SKILL.md folders loaded when relevant. | **Has.** Skill packs, scanned first; only fitting skills used. | Custom modes. | tests |
| Ignore files | Keep files away from the agent. | **Partly.** Private notes never sent to a model; `.env` and `~/.ssh` denied to jobs. | A per-project ignore file. | tests |
| Codebase search | Local index for exact and regex search. | **Partly.** The coding agents search the code; JARVIS searches notes and chats. | An index of its own. | code |
| Web search | The agent searches the web. | **Has.** Research, and pages read as data. | — | real |
| Inline edit and Tab completion | Cmd+K; AI autocomplete as you type. | **Missing**: JARVIS is not an editor. | — | — |
| Agent, Ask and Plan modes | Build; read-only questions; a plan to edit, then build. | **Has.** Chat mode and Code mode; planner and builder with a plan you can change. | — | real |
| Debug mode | Adds logging, reproduces, fixes, removes logging. | **Missing.** | — | — |
| Diff review and reject | Edits shown as a diff; reject any. | **Has.** Review before merge; undo after. | Rejecting single hunks. | real |
| Checkpoints | Restore files to an earlier message. | **Partly.** Undo a merged job; restore points for settings. | Restoring to any message. | real |
| Stop, queue and steer | Stop; queued follow-ups; steer at the next tool call. | **Partly.** Stop; answer a job's question. | Queue and steer. | real |
| Goals and /loop | Work toward a goal; repeat a prompt on an interval. | **Partly.** Routines repeat a request on a schedule. | `/goal`. | tests |
| Agent review and Bugbot | Review local changes or each pull request for bugs and security. | **Partly.** The security check and fix; jobs are reviewed before merge. | Pull request review. | real |
| Voice chat and dictation | Spoken conversation; dictation to review. | **Has**, and the wake word, dictation into any app, and the computer's own sound ignored. | — | real Mac, tests |
| Design Mode | Notes on a running app become code changes. | **Missing.** | — | — |
| Agents Window and Projects | Many agents across projects; a coordinator delegating. | **Partly.** The Agents panel; agent teams (planner and builder, Court). | A coordinator for large work. | real |
| Terminal commands and run modes | Auto-review, allowlist, run everything; sandbox. | **Has**, differently: jobs have no shell; JARVIS runs the project's checks itself; the assistant's commands follow the ways of asking. | — | real |
| Subagents | Specialised helpers with their own context. | **Partly.** Planner and builder; Court's analysts. | Custom subagents. | real |
| Hooks | Scripts at each step that allow, block or change it. | **Missing.** | Hooks. | — |
| Plugins and marketplace | Bundles of rules, skills, MCP servers, hooks. | **Partly.** Skill packs and mods, installed only after a scan. | A marketplace. | tests |
| MCP servers and approval | Connect external tools; approve each call. | **Partly.** Connected online accounts through Composio, scoped to what you connected; sending, deleting and paying always asked. | Your own MCP servers. | code |
| Browser tool | The agent drives a browser and reads console and network. | **Partly.** The assistant opens, reads, presses and types in pages and apps; step-by-step control from pictures. | Console and network reading. | real Mac |
| Image generation | Images from text, saved to the project. | **Has.** Pictures made in the chat. | Saving into a project. | code |
| Model picker, effort, Auto routing | Switch models; Auto by cost or intelligence. | **Has.** JARVIS chooses by the size of the task; you can choose the model and effort; the model that answered is named. | — | real |
| Usage pools and caps | One weekly pool; a monthly spend cap. | **Has**, differently: budgets you set per day, task and project; nothing is ever bought. | — | tests |
| Cloud agents, environments, handoff to cloud | Agents on cloud machines that run with the laptop off. | **Not wanted** (local only). | — | — |
| Automations on events | Cron or events from GitHub, Slack, Linear and others. | **Partly.** Routines on a schedule. | Event triggers. | tests |
| Mobile app and remote control | Start and steer agents from a phone. | **Not wanted** (desktop only). | — | — |
| Security review and remediation | Reviewer agents; scheduled scans; draft fix PRs. | **Has**, locally: the security check finds holes, a job fixes the ones you choose in a copy, and the fix waits for your review. | Scheduled scans (a routine can do it). | real |
| PR routing and approval | An agent requests reviewers and approves low-risk PRs. | **Missing.** | — | — |
| CLI (interactive, print mode, ACP server) | `agent` in a terminal; `-p` for scripts; ACP for other editors. | **Partly.** `jcc` commands (`jcc test-providers`, jobs, voice checks). | An interactive CLI; ACP. | code |
| Slack, Linear, Jira, Teams, Notion | Start agents from those apps. | **Partly.** JARVIS can read and act in connected accounts on request. | Starting work from those apps. | code |
| JetBrains and Xcode | Cursor's agent inside those IDEs. | **Not wanted.** | — | — |
| Privacy Mode | No training on your code; zero retention for most models. | **Has**, differently: everything runs on your computer; private notes are never sent; keys never leave the key store. What the AI services keep is their own policy. | — | tests |

## The gaps most worth closing

In order of use to JARVIS's owner, as this table sees it:

1. `@` mentions in the message box (files, chats, a project's code) and citing part of a reply.
2. Steering a running job and queueing a follow-up, rather than only Stop and answering questions.
3. Side chats about a job or a chat that do not disturb it.
4. Restoring a project to how it was at any message (checkpoints), not only undoing a whole job.
5. Pull requests: open, review and merge from JARVIS for projects kept on GitHub.
6. Routines started by events (a new pull request, a failing check), not only by the clock.
7. Hooks, and your own MCP servers, for people who extend their tools.
8. More coding agents: Cursor's CLI, OpenCode, and agents that speak ACP.
