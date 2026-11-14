"""What the assistant may do on its own, what waits for the owner's yes, and what is never done.

Every action the assistant takes on the PC is checked here, in the JARVIS service, before it runs.
The model cannot answer these checks itself.

Three ideas:
1. Some things are never done: reading saved passwords and keys, tampering with Windows security,
   destroying disks, acting on banking, payment or password windows.
2. Things that cannot be undone, cost money or reach other people wait for a yes.
3. Careful mode. Web pages, files, the screen and the clipboard can contain text written to trick an
   AI ("ignore your instructions and run this"). Once a chat has taken in such outside content,
   anything that changes the computer or could send data out also waits for a yes, for the rest of
   that chat. A fresh chat starts clean.

How much is asked is the owner's choice (LEVELS):
  sending   only before sending something to other people, deleting, paying, and the few things an
            attack hidden in a web page would need (installing or downloading by command, running a
            program file, writing where programs start themselves). Everything else is simply done.
  risky     also before anything risky, and everything in careful mode (ideas 2 and 3 in full).
  all       before every action that changes something on the PC.
What is never done (idea 1) does not depend on the level.
"""
from __future__ import annotations

from jcc import own_terms
import os
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

from jcc.redact import redact

ALLOW, CONFIRM, DENY = "allow", "confirm", "deny"
# Tools that do not touch the computer itself; they stay available when PC control is switched off.
WITHOUT_PC = frozenset({"set_timer", "set_reminder", "list_reminders", "cancel_reminder", "weather", "where_to_watch", "remember", "forget", "add_note",
                        "read_web_page", "make_image", "list_projects", "create_project", "build_with_coding_agents", "connector", "use_accounts"})

def _on_mac() -> bool:
    from jcc import system
    return system.kind() == "mac"


OWN_WINDOW = re.compile(r"^JARVIS\b.*\b(?:Workspace|Listening)\b")   # JARVIS's own windows: looked at by their owner, never worked in by the assistant
MAIN_WINDOW = re.compile(r"^JARVIS\b.*\bWorkspace\b")    # ... the app window itself (the other is the small "listening" window)
PRIVATE_WINDOW = re.compile(
    r"bank|netbank|paypal|payment|checkout|wallet|1password|bitwarden|keepass|lastpass|dashlane|credential manager|"
    r"windows security|user account control|zerodha|groww|upstox|coinbase|binance" + own_terms.alternation(), re.I)
MESSAGING_WINDOW = re.compile(
    r"whatsapp|telegram|signal|discord|slack|microsoft teams|\bteams\b|messenger|instagram|facebook|twitter|linkedin|gmail|"
    r"outlook|\bmail\b|thunderbird|proton|\bmessages\b|skype|wechat|snapchat|reddit|compose|new message|inbox", re.I)
TERMINAL_WINDOW = re.compile(
    r"powershell|command prompt|cmd\.exe|windows terminal|\bterminal\b|pwsh|\bbash\b|ubuntu|\bwsl\b|mingw|^run$|registry editor|"
    r"task scheduler|group policy", re.I)
LEVELS = ("sending", "risky", "all")
# Tools that only look, or change nothing that matters: never asked about, even at the "all" level.
QUIET_TOOLS = frozenset({"see_screen", "list_controls", "list_windows", "find_files", "read_file", "read_web_page", "weather", "list_reminders",
                         "list_projects", "wait", "find_videos", "read_clipboard", "scroll", "set_timer", "set_reminder", "cancel_reminder",
                         "set_volume", "set_brightness", "media", "focus_window", "move_window", "where_to_watch"})
# Windows where Enter sends what was typed (chat apps and public posts). In a mail window only ctrl+enter sends.
CHAT_WINDOW = re.compile(
    r"whatsapp|telegram|signal|discord|slack|microsoft teams|\bteams\b|messenger|instagram|facebook|twitter|linkedin|\bmessages\b|skype|wechat|"
    r"snapchat|reddit", re.I)
_EXTRA = r"(?:\s*[(\[][^)\]]{0,24}[)\]])?"       # "Send (Ctrl-Enter)", "Delete [Del]"
SEND_BUTTON = re.compile(r"^\W*(send|send now|send message|send email|send mail|send reply|post|post reply|publish|tweet|reply|reply all|forward|share|"
                         r"submit post|comment)" + _EXTRA + r"\W*$", re.I)
DELETE_BUTTON = re.compile(r"^\W*(delete|delete forever|delete permanently|delete all|remove|uninstall|format|reset|erase|discard|discard draft|"
                           r"empty (recycle bin|trash|bin)|move to (trash|bin|recycle bin))" + _EXTRA + r"\W*$", re.I)
PAY_BUTTON = re.compile(r"^\W*(pay|pay now|buy|buy now|purchase|place( your)? order|order now|checkout|check out|proceed to (checkout|pay|payment)|"
                        r"confirm (purchase|order|payment)|transfer|donate|subscribe|complete (purchase|order))" + _EXTRA + r"\W*$", re.I)
OUTWARD_BUTTON = re.compile(
    r"^\W*(send|post|publish|tweet|reply|reply all|forward|submit|share|pay|pay now|buy|buy now|purchase|place( your)? order|order now|"
    r"checkout|check out|confirm|confirm (purchase|order|payment)|delete|delete forever|remove|uninstall|format|reset|erase|"
    r"sign out|log out|transfer|donate|subscribe|unsubscribe|empty (recycle bin|trash)|accept|agree|i agree|allow|install|run anyway)\W*$", re.I)

SECRET_PATH = re.compile(
    r"(^|[\\/])(\.ssh|\.aws|\.azure|\.kube|\.gnupg|\.docker|credentials?|secrets?)([\\/]|$)|"
    r"\.(env|pem|key|pfx|p12|kdbx|ppk|ovpn)$|(^|[\\/])\.env(\.[\w-]+)?$|id_(rsa|ed25519|ecdsa|dsa)|\.git-credentials|\.netrc|wallet\.dat|"
    r"(login data|cookies|web data|local state|logins\.json|key[34]\.db)$|microsoft[\\/](credentials|protect)[\\/]|"
    r"jarviscommand[\\/](browser-sync-key|webview-profile|window-profile|assistant[\\/])|^[a-z]:[\\/]windows([\\/]|$)|"
    r"ntuser\.dat|[\\/]config[\\/](sam|security|system)$|(^|[\\/])library[\\/]keychains([\\/]|$)|^/(system|private/etc|etc)(/|$)|"
    r"(^|[\\/])firefox[\\/]profiles[\\/]", re.I)
DANGEROUS_PLACE = re.compile(
    r"start menu[\\/]programs[\\/]startup|microsoft\.powershell_profile|[\\/]profile\.ps1$|\.bashrc$|\.bash_profile$|\.zshrc$|"
    r"drivers[\\/]etc[\\/]hosts|[\\/]system32[\\/]|\.gitconfig$|settings\.json$|library[\\/]launch(agents|daemons)[\\/]|\.zprofile$|\.zshenv$|\.zlogin$|"
    r"(^|[\\/])\.profile$|(^|[\\/])\.config[\\/]autostart[\\/]|/etc/(hosts|crontab|profile)$", re.I)

BLOCKED_COMMAND = re.compile(
    r"format-volume|\bformat\s+[a-z]:|diskpart|clear-disk|remove-partition|initialize-disk|bcdedit|cipher\s+/w|vssadmin|wbadmin|"
    r"disable-computerrestore|mimikatz|sekurlsa|procdump|lsass|ntds\.dit|cmdkey|vaultcmd|credentialmanager|get-storedcredential|"
    r"convertfrom-securestring|\.ssh[\\/]|id_(rsa|ed25519|ecdsa)|\.git-credentials|\.aws[\\/]credentials|wallet\.dat|"
    r"(google[\\/]chrome|microsoft[\\/]edge|bravesoftware|mozilla[\\/]firefox).{0,80}(login data|cookies|web data|local state|logins\.json|key4\.db)|"
    r"microsoft[\\/](credentials|protect)\b|jarviscommand[\\/](browser-sync-key|webview-profile|window-profile|assistant)|"
    r"set-mppreference|add-mppreference|netsh\s+advfirewall|set-netfirewallprofile|enablelua|clear-eventlog|wevtutil\s+cl|"
    r"reg(\.exe)?\s+(add|delete|save)\s+\"?hklm|[\\/]config[\\/](sam|security)\b|"
    r"\bsecurity\s+(find-(generic|internet)-password|dump-keychain|export|delete-(generic|internet)-password|add-(generic|internet)-password|unlock-keychain)|"
    r"library[\\/]keychains|\bsecret-tool\s+(lookup|search|clear|store)|\bdiskutil\s+(erase\w*|zero\w*|secureerase|partition\w*|apfs\s+delete\w*)|"
    r"\bcsrutil\b|\bspctl\s+--master-disable|\bfdesetup\b|\btmutil\s+delete|\bnvram\b|\bmkfs(\.\w+)?\b|\bdd\b[^|;]*\bof=/dev/|"
    r"firefox[\\/]profiles.{0,80}(logins\.json|key4\.db|cookies)|/etc/(shadow|sudoers|master\.passwd)|"
    r"(remove-item|rm|del|rd|rmdir|ri)\b[^|;]*\s(?P<q>['\"]?)([a-z]:[\\/]?|~[\\/]?|\$home[\\/]?|\$env:userprofile[\\/]?|[a-z]:[\\/]users([\\/][^\\/\s'\"]+)?[\\/]?|[a-z]:[\\/]windows\S*|/|/\*|\$home/?|/(users|home)(/[^/\s'\"]+)?/?|/(system|library|applications|usr|bin|sbin|etc|var|private)\S*)(?P=q)(\s|$)",
    re.I)
RISKY_COMMAND = re.compile(
    r"\b(remove-item|del|erase|rd|rmdir|rm|ri|clear-content|clear-recyclebin|stop-computer|restart-computer|shutdown|logoff|"
    r"uninstall-\w+|winget|choco|scoop|msiexec|install-module|install-package|install-script|add-appxpackage|"
    r"pip3?\s+(install|uninstall)|npm\s+(i|install|uninstall|publish)|npx|yarn\s+(add|global)|pnpm\s+(add|i|install)|"
    r"reg(\.exe)?\s+(add|delete|import)|set-itemproperty|new-itemproperty|remove-itemproperty|schtasks|register-scheduledtask|"
    r"new-service|sc(\.exe)?\s+(create|config|delete)|net(\.exe)?\s+(user|localgroup|share)|set-executionpolicy|"
    r"send-mailmessage|git\s+(push|remote\s+add|config\s+--global)|taskkill|stop-process|kill|move-item|mv|move|rename-item|ren|"
    r"invoke-webrequest|iwr|invoke-restmethod|irm|curl(\.exe)?|wget(\.exe)?|start-bitstransfer|bitsadmin|certutil|"
    r"invoke-expression|iex|invoke-command|icm|start-job|"
    r"ssh|scp|sftp|ftp|ncat|nc|telnet|docker|wsl|runas|mshta|rundll32|regsvr32|wscript|cscript|"
    r"sudo|su|doas|launchctl|defaults\s+(write|delete)|brew\s+(install|uninstall|reinstall|tap|upgrade)|port\s+install|apt(-get)?\s+(install|remove|purge)|dnf|yum|pacman|snap\s+install|flatpak\s+install|osascript|crontab|chmod|chown|chflags|xattr\s+-[dc]|pkill|killall|systemctl|reboot|halt|pbcopy|xclip|xsel|"
    r"compress-archive|expand-archive|tar|7z|"
    r"set-clipboard|clip(\.exe)?|attrib|icacls|takeown|set-acl|new-netfirewallrule|netsh)\b|"
    r"-encodedcommand|\s-enc\s|-verb\s+runas|downloadstring|downloadfile|net\.webclient|\[scriptblock\]|frombase64string", re.I)
# Among the risky commands: the ones that delete, and the ones an attack would use (fetch and run code, install, change
# how Windows starts or who may do what, reach other machines). These are asked about at every level.
DELETE_COMMAND = re.compile(r"\b(remove-item|del|erase|rd|rmdir|rm|ri|clear-content|clear-recyclebin|uninstall-\w+)\b|git\s+clean\b", re.I)
SYSTEM_COMMAND = re.compile(
    r"\b(winget|choco|scoop|msiexec|install-module|install-package|install-script|add-appxpackage|"
    r"pip3?\s+(install|uninstall)|npm\s+(i|install|uninstall|publish)|npx|yarn\s+(add|global)|pnpm\s+(add|i|install)|"
    r"reg(\.exe)?\s+(add|delete|import)|set-itemproperty|new-itemproperty|remove-itemproperty|schtasks|register-scheduledtask|"
    r"new-service|sc(\.exe)?\s+(create|config|delete)|net(\.exe)?\s+(user|localgroup|share)|set-executionpolicy|"
    r"send-mailmessage|git\s+(push|remote\s+add|config\s+--global)|"
    r"invoke-webrequest|iwr|invoke-restmethod|irm|curl(\.exe)?|wget(\.exe)?|start-bitstransfer|bitsadmin|certutil|"
    r"invoke-expression|iex|invoke-command|icm|start-job|"
    r"ssh|scp|sftp|ftp|ncat|nc|telnet|docker|wsl|runas|mshta|rundll32|regsvr32|wscript|cscript|"
    r"sudo|su|doas|launchctl|defaults\s+(write|delete)|brew\s+(install|uninstall|reinstall|tap|upgrade)|port\s+install|apt(-get)?\s+(install|remove|purge)|dnf|yum|pacman|snap\s+install|flatpak\s+install|osascript|crontab|chmod|chown|chflags|xattr\s+-[dc]|pkill|killall|systemctl|reboot|halt|"
    r"icacls|takeown|set-acl|new-netfirewallrule|netsh)\b|"
    r"-encodedcommand|\s-enc\s|-verb\s+runas|downloadstring|downloadfile|net\.webclient|\[scriptblock\]|frombase64string", re.I)
_SUSPECT_FACT = re.compile(r"https?://|powershell|cmd\.exe|\bignore\b.{0,30}\b(instruction|rule)|system prompt|password|api key|\btoken\b", re.I)
_READ_ONLY = {
    "get-childitem", "gci", "dir", "ls", "get-content", "gc", "cat", "type", "get-item", "gi", "test-path", "resolve-path",
    "get-location", "pwd", "gl", "set-location", "cd", "sl", "get-date", "date", "get-process", "gps", "ps", "get-service", "gsv",
    "get-command", "gcm", "where.exe", "where", "whoami", "hostname", "systeminfo", "get-computerinfo", "get-ciminstance",
    "get-volume", "get-disk", "get-psdrive", "get-startapps", "get-package", "get-appxpackage", "get-hotfix", "get-filehash",
    "measure-object", "measure", "select-object", "select", "where-object", "sort-object", "sort", "group-object", "group",
    "format-table", "ft", "format-list", "fl", "out-string", "select-string", "sls", "findstr", "tree", "echo", "write-output",
    "write-host", "tasklist", "ver", "get-timezone", "get-culture", "get-uptime", "get-history", "split-path", "join-path",
    "get-acl", "get-itemproperty", "get-itempropertyvalue", "get-random", "get-host", "get-module"}
_GIT_READ = {"status", "log", "diff", "show", "branch", "rev-parse", "describe", "ls-files", "blame", "tag", "remote", "stash"}
_READS_CONTENT = re.compile(r"\b(get-content|gc|cat|type|select-string|sls|findstr|more|get-clipboard|pbpaste|head|tail|less|grep|xclip|xsel)\b", re.I)
RUNNABLE = re.compile(r"\.(exe|bat|cmd|com|ps1|psm1|vbs|vbe|js|jse|wsf|wsh|msi|msix|appx|scr|hta|reg|lnk|url|jar|py|pyw|cpl|dll|gadget|inf|pif|application)$", re.I)


@dataclass
class Context:
    exposed: bool = False        # the chat has taken in outside content (careful mode)
    private: bool = False        # the chat has seen the owner's own data
    confirm_risky: bool = True   # at the "risky" level: False leaves out the questions that are not about careful mode
    level: str = "risky"         # how much the owner wants to be asked: one of LEVELS
    window: str = ""             # title of the window in front, for input tools
    control: str = ""            # name of the control about to be pressed, when known
    vault: str = ""              # the notes vault, whose Private folder is off limits
    app_dir: str = ""            # where JARVIS itself is installed: changing it needs a yes
    state_dir: str = ""          # JARVIS's own settings folder: off limits


@dataclass
class Decision:
    verdict: str
    kind: str = ""               # risky | send | careful | all (why a yes is needed)
    question: str = ""
    detail: str = ""
    reason: str = ""             # shown to the model when refused
    core: bool = False           # asked at every level: sending, deleting, paying, or what an attack would need

    @property
    def must_ask(self) -> bool:
        return self.verdict == CONFIRM


def _allow() -> Decision:
    return Decision(ALLOW)


def _deny(reason: str) -> Decision:
    return Decision(DENY, reason=reason)


def _ask(kind: str, question: str, detail: str = "", core: bool = False) -> Decision:
    return Decision(CONFIRM, kind, question[:200], redact(detail)[:700], core=core)


def _visible(name: str) -> str:
    """A control's name without the invisible marks some pages put in it (Gmail's Send button has them)."""
    return " ".join("".join(c for c in str(name) if unicodedata.category(c) not in ("Cf", "Cc")).split())


def command_core(command: str) -> bool:
    """Whether a command deletes something, or is of the kind an attack would use. Asked about at every level."""
    text = " ".join(str(command).split())
    return bool(DELETE_COMMAND.search(text) or SYSTEM_COMMAND.search(text))


def command_kind(command: str) -> str:
    """blocked | risky | read (changes nothing) | normal."""
    text = " ".join(str(command).split())
    if BLOCKED_COMMAND.search(text):
        return "blocked"
    if RISKY_COMMAND.search(text):
        return "risky"
    if any(mark in text for mark in (">", "{", "$(", "`", "\n")) or re.search(r"\$(?!env:\w+|home\b|pwd\b|null\b|true\b|false\b|_\b)", text, re.I):
        return "normal"
    for segment in re.split(r"[|;]|&&|\|\|", text):
        words = segment.strip().split()
        if not words:
            continue
        first = words[0].lower().strip("&")
        if first == "git" and len(words) > 1 and words[1].lower() in _GIT_READ and not re.search(r"\b(add|remove|rm|set-url|drop|pop|clear|-d|-D)\b", segment):
            continue
        if len(words) == 2 and words[1].lower() in ("--version", "-v", "-version", "version"):
            continue
        if first not in _READ_ONLY:
            return "normal"
    return "read"


def reads_content(command: str) -> bool:
    return bool(_READS_CONTENT.search(str(command)))


def _norm(path: str) -> str:
    try:
        # Lower case on every system: a Mac's disk ignores case too, so "Vault/private" must count as "Vault/Private".
        text = os.path.expandvars(os.path.expanduser(str(path)))
        if os.sep != "\\":
            text = text.replace("\\", "/")          # a path written the Windows way is still a path: "..\Private" must not slip past
        return os.path.normcase(os.path.realpath(text)).replace("/", "\\").lower()
    except (OSError, ValueError):
        return str(path).lower().replace("/", "\\")


def inside(path: str, folder: str) -> bool:
    if not folder:
        return False
    target, base = _norm(path), _norm(folder).rstrip("\\")
    return target == base or target.startswith(base + "\\")


def path_problem(path: str, vault: str = "", state_dir: str = "") -> str | None:
    text = str(path)
    if SECRET_PATH.search(text) or SECRET_PATH.search(_norm(text)):
        return "JARVIS does not open or change password, key, browser-profile or Windows system files."
    if vault and inside(text, os.path.join(vault, "Private")):
        return "Notes in your Private folder are never shown to an AI."
    if state_dir and inside(text, state_dir):
        return "JARVIS's own settings folder is off limits."
    return None


def decide(tool: str, args: dict, ctx: Context) -> Decision:
    """The single place where an assistant action is allowed, held for a yes, or refused."""
    decision = _decide(tool, args, ctx)
    if ctx.level == "all" and decision.verdict == ALLOW and tool not in QUIET_TOOLS:
        given = args if isinstance(args, dict) else {}
        what = {"open_app": "open " + str(given.get("name", "that app"))[:40], "open_website": "open that web page", "open_file": "open that file",
                "click": "click there", "click_control": "press “" + (ctx.control or str(given.get("name", "")))[:40] + "”",
                "type_text": "type that", "type_into": "type that", "press_keys": "press " + str(given.get("keys", "that key"))[:30],
                "run_command": "run that command", "write_file": "write that file", "play_music": "play that", "play_show": "put that on",
                "write_email": "write that email"}.get(tool, "use " + tool.replace("_", " "))
        return _ask("all", f"Shall I {what}?", redact(str(given))[:300])
    return decision


def _decide(tool: str, args: dict, ctx: Context) -> Decision:
    args = args if isinstance(args, dict) else {}
    careful = ctx.exposed
    input_tool = tool in ("click", "type_text", "press_keys", "scroll", "click_control", "type_into", "see_screen", "list_controls")
    if input_tool and PRIVATE_WINDOW.search(ctx.window or ""):
        return _deny("A private window (banking, payment, passwords or security) is in front. Ask the user to do this part themselves.")
    if input_tool and OWN_WINDOW.search(ctx.window or ""):
        return _deny("That is JARVIS's own window. Use focus_window to choose the app or page to work in.")

    if tool in ("open_app", "list_projects", "create_project", "set_timer", "set_reminder", "list_reminders", "cancel_reminder",
                "add_note", "scroll", "see_screen", "list_controls", "media", "list_windows", "focus_window", "move_window", "wait", "set_volume",
                "set_brightness", "lock_pc", "find_files", "read_clipboard", "write_clipboard", "play_music", "play_show", "write_email"):
        return _allow()

    if tool == "connector":
        # A tool from a connector the owner added (Gmail, a calendar...). Trusted in a clean chat; asked about in careful mode.
        name = str(args.get("tool", "")).split("__")[-1].replace("_", " ")[:60] or "a connector"
        if re.search(r"\b(send|reply|forward|post|publish|delete|remove|trash|pay|purchase|buy|transfer)\b", name, re.I):
            return _ask("send", f"Shall I use {name}?", str(args.get("input", "")), core=True)
        return _ask("careful", f"Shall I use {name}?", str(args.get("input", ""))) if careful else _allow()

    if tool == "use_accounts":
        # The owner's email, calendar and other online accounts (jcc/online.py). Looking something up is done by a helper
        # that can only read. Anything that sends, creates, changes or deletes is always the owner's call, whatever the
        # setting: it is done in their name, out in the world.
        request = str(args.get("request", ""))
        if args.get("change"):
            return _ask("send", "Shall I do this in your online accounts?", request, core=True)
        return _ask("careful", "Shall I look this up in your online accounts?", request) if careful else _allow()

    if tool in ("remember", "forget"):
        # Memory is read at the start of every future chat, so outside content must not be able to write it.
        fact = str(args.get("fact") or args.get("words") or "")
        if careful:
            return _ask("careful", "Shall I change what I remember about you?", fact, core=tool == "remember" and bool(_SUSPECT_FACT.search(fact)))
        return _allow()

    if tool == "build_with_coding_agents":
        return _ask("careful", "Shall I start the coding agents on this?", str(args.get("task", ""))) if careful else _allow()

    if tool in ("make_image", "weather"):
        if careful and ctx.private:
            return _ask("careful", "Shall I send this to an outside service?", str(args.get("description") or args.get("place") or ""))
        return _allow()

    if tool == "where_to_watch":
        return _allow()                 # (only the title and the country go to the lookup)
    if tool == "find_videos":
        return _ask("careful", "Shall I search YouTube for this?", str(args.get("query", ""))) if careful and ctx.private else _allow()

    if tool in ("open_website", "read_web_page"):
        if args.get("search"):
            return _allow()
        target = str(args.get("address_or_search") or args.get("url") or "")
        parsed = urlparse(target if re.match(r"^https?://", target, re.I) else "")
        if not parsed.hostname:
            return _allow()
        carries_data = bool(parsed.query) or len(parsed.path) > 90 or bool(parsed.fragment)
        if careful and ctx.private and carries_data:
            # A search is a few words. A long address could be carrying the owner's own data away: that is asked about at every level.
            return _ask("careful", "Open this web address?", target, core=len(parsed.query) + len(parsed.fragment) > 160 or len(parsed.path) > 160)
        return _allow()

    if tool in ("click", "click_control"):
        name = _visible(ctx.control or str(args.get("name") or ""))
        where = f" in {ctx.window[:50]}?" if ctx.window else "?"
        if name and SEND_BUTTON.search(name):
            return _ask("send", f"Shall I press “{name.strip()[:40]}”" + where, "This sends it.", core=True)
        if name and DELETE_BUTTON.search(name):
            return _ask("send", f"Shall I press “{name.strip()[:40]}”" + where, "This deletes or removes something.", core=True)
        if name and PAY_BUTTON.search(name):
            return _ask("send", f"Shall I press “{name.strip()[:40]}”" + where, "This may spend money.", core=True)
        if name and OUTWARD_BUTTON.search(name):
            return _ask("send", f"Shall I press “{name.strip()[:40]}”" + where, "This may send, buy, delete or agree to something.")
        if tool == "click" and not name and careful and MESSAGING_WINDOW.search(ctx.window or ""):
            return _ask("careful", f"Shall I click in {ctx.window[:50]}?", "JARVIS cannot tell what this button does. It could be Send.", core=True)
        return _allow()

    if tool in ("type_text", "type_into"):
        text = str(args.get("text", ""))
        if redact(text) != text:
            return _deny("That looks like a password or key. JARVIS never types those; ask the user to type it.")
        enter = bool(args.get("press_enter"))
        if TERMINAL_WINDOW.search(ctx.window or ""):
            if command_kind(text) == "blocked":
                return _deny("JARVIS does not type commands that touch disks, saved passwords, browser profiles or Windows security.")
            return _ask("risky", "Shall I type this into the command window?", text, core=command_core(text))
        if enter and MESSAGING_WINDOW.search(ctx.window or ""):
            # In a chat app Enter sends. In a mail window it only starts a new line (ctrl+enter is what sends there).
            return _ask("send", f"Shall I send this in {ctx.window[:50]}?", text, core=bool(CHAT_WINDOW.search(ctx.window or "")))
        return _allow()

    if tool == "press_keys":
        keys = set(str(args.get("keys", "")).lower().replace(" ", "").split("+"))
        if _on_mac():
            from jcc import macdesk
            keys = macdesk.plain_keys(keys)            # ("command" and "win" are cmd, "option" is alt)
            if macdesk.never(keys):
                return _deny("That shortcut is reserved for macOS: it logs out, locks the Mac or force-quits.")
            if keys == {"cmd", "space"}:
                return _ask("risky", "Shall I open Spotlight?", "It can start any program.")
            if {"cmd", "alt"} <= keys and ({"delete", "del", "backspace"} & keys):
                return _ask("risky", "Shall I press " + "+".join(sorted(keys)) + "?", "This deletes for good, skipping the Trash.", core=True)
            if keys in ({"cmd", "delete"}, {"cmd", "del"}, {"cmd", "backspace"}):
                return _ask("careful" if careful else "risky", "Shall I press Command-Delete" + (f" in {ctx.window[:50]}?" if ctx.window else "?"),
                            "This moves what is selected to the Trash.", core=True)
            if careful and keys in ({"cmd", "q"}, {"cmd", "w"}, {"cmd", "shift", "w"}):
                return _ask("careful", "Shall I press " + "+".join(sorted(keys)) + "?", "This closes something.")
        if {"ctrl", "alt"} <= keys and ({"delete", "del"} & keys):
            return _deny("That shortcut is reserved for Windows.")
        if "enter" in keys or "return" in keys:
            if TERMINAL_WINDOW.search(ctx.window or ""):
                return _ask("risky", "Shall I press Enter in the command window?", "This runs whatever is typed there.")
            if MESSAGING_WINDOW.search(ctx.window or ""):
                sends = "ctrl" in keys or "cmd" in keys or bool(CHAT_WINDOW.search(ctx.window or ""))   # ctrl+enter (cmd+enter on a Mac) sends mail; Enter sends a chat message
                return _ask("send", f"Shall I send this in {ctx.window[:50]}?" if sends else f"Shall I press Enter in {ctx.window[:50]}?",
                            "This sends the message." if sends else "This may send a message.", core=sends)
        if keys in ({"win", "r"}, {"win", "x"}):
            return _ask("risky", "Shall I open the Run box?" if "r" in keys else "Shall I open the power-user menu?", "It can start any program.")
        if keys == {"shift", "delete"}:
            return _ask("risky", "Shall I press shift+delete?", "This deletes for good, skipping the Recycle Bin.", core=True)
        if keys in ({"delete"}, {"del"}):
            return _ask("careful" if careful else "risky", "Shall I press Delete" + (f" in {ctx.window[:50]}?" if ctx.window else "?"),
                        "This deletes what is selected.", core=True)
        if careful and keys in ({"alt", "f4"}, {"ctrl", "w"}, {"ctrl", "shift", "w"}):
            return _ask("careful", "Shall I press " + "+".join(sorted(keys)) + "?", "This closes something.")
        return _allow()

    if tool == "run_command":
        command = str(args.get("command", ""))
        kind = command_kind(command)
        if kind == "blocked":
            return _deny("JARVIS does not run commands that touch disks, saved passwords, browser profiles or Windows security.")
        low = command.lower().replace("/", "\\")
        for folder, why in ((ctx.state_dir, "JARVIS's own settings"), (ctx.app_dir, "JARVIS's own program")):
            if folder and folder.lower().replace("/", "\\").rstrip("\\") in low and kind != "read":
                return _ask("risky", "Shall I run this command?", command + "\nIt touches " + why + ".", core=True)
        if kind == "risky":
            return _ask("risky", "Shall I run this command?", command, core=command_core(command))
        if kind == "normal" and careful:
            return _ask("careful", "Shall I run this command?", command)
        return _allow()

    if tool in ("read_file", "write_file", "open_file"):
        path = str(args.get("path", ""))
        problem = path_problem(path, ctx.vault, ctx.state_dir)
        if problem:
            return _deny(problem)
        name = path.replace(chr(92), "/").rsplit("/", 1)[-1]
        if tool == "read_file":
            return _allow()
        if tool == "open_file":
            if RUNNABLE.search(path):
                return _ask("risky", f"Shall I run {name}?", path + "\nThis starts a program or script.", core=True)
            return _ask("careful", f"Shall I open {name}?", path) if careful else _allow()
        if inside(path, ctx.app_dir):
            return _ask("risky", "Shall I change JARVIS's own program?", path, core=True)
        if DANGEROUS_PLACE.search(path) or DANGEROUS_PLACE.search(_norm(path)):
            return _ask("risky", "Shall I write to this file?", path + "\nPrograms read this file when they start.", core=True)
        if args.get("exists") and not args.get("own"):     # (a file JARVIS itself wrote in this conversation may be rewritten)
            return _ask("risky", f"Shall I replace the file {name}?", path + "\nWhat it holds now would be lost.", core=True)
        if careful:
            return _ask("careful", "Shall I create this file?", path)
        return _allow()

    if tool == "send_email":
        return _ask("send", f"Shall I send this email to {str(args.get('to', ''))[:80]}?",
                    f"Subject: {args.get('subject', '')}\n\n{args.get('body', '')}", core=True)

    return _ask("careful" if careful else "risky", f"Shall I use {tool.replace('_', ' ')}?", redact(str(args))[:300], core=True)


def needs_owner(decision: Decision, ctx: Context) -> bool:
    """Whether to actually stop and ask: that depends on how much the owner wants to be asked (LEVELS)."""
    if decision.verdict != CONFIRM:
        return False
    if ctx.level == "sending":
        return decision.core
    if ctx.level == "all":
        return True
    return decision.kind == "careful" or ctx.confirm_risky or ctx.exposed      # in careful mode every question is asked


def marks(tool: str, args: dict) -> tuple[bool, bool]:
    """(exposed, private) the chat becomes after this tool has returned its result to the model."""
    short = tool.split("__")[-1]
    if short in ("WebSearch", "WebFetch", "read_web_page", "find_videos", "where_to_watch"):
        return True, False
    if short in ("read_file", "see_screen", "list_controls", "read_clipboard", "list_windows"):
        return True, True
    if short == "find_files":
        return False, True
    if short == "run_command":
        return reads_content(str((args or {}).get("command", ""))), True
    if short == "list_projects":
        return False, True
    if short == "use_accounts":
        return True, True  # emails and invitations are other people's writing, and the owner's own business
    if short == "connector" or (tool.startswith("mcp__") and not tool.startswith("mcp__jarvis__")):
        return True, True  # a connector the owner added: its output is outside content
    return False, False
