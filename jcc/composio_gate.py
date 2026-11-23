"""The gate between the helper for online accounts and Composio, for an owner whose Composio key starts with ck_.

A ck_ key ("consumer" key) reaches only Composio's ready-made server (connect.composio.dev/mcp), which offers every tool
it has to whoever holds the key: a remote computer, raw requests to an app's own API, and one tool that runs any app's
tools (send an email as readily as read one). Composio cannot be asked to hold any of that back for such a key, as it is
for a project key (ak_, jcc/online.py). So JARVIS does it on this PC: the helper is not given Composio's server but this
small one, run by JARVIS itself, which holds the key and passes on only what the request's kind allows:

- read (looking something up, no one asked): the search, the tool descriptions, and running app tools whose names say
  that they read, of apps the owner has connected. Anything else ("send", "create", "delete"... or a name that does not
  say) is refused, and the helper says that it needs the owner's yes.
- act (the owner said yes to a change): the same, and app tools of any kind, still only of connected apps.
- connect (the owner said yes to connecting or removing an account): the search, and connecting, listing and removing
  accounts. Nothing is run in an app.

Never, in any kind: Composio's remote computer and shell, raw requests, its skills, its feedback form, Composio's own
tools run through the tool that runs tools, and the workbench copy of results. Which kind, and which apps, is decided by
JARVIS on its command line (python -m jcc.composio_gate read gmail,googlecalendar): the helper cannot change it.

The key comes from Windows Credential Manager (or, failing that, the helper's environment, which this gate then clears).
It is only ever sent to connect.composio.dev, and no redirect is followed with it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from jcc.redact import redact, register_secret

URL = "https://connect.composio.dev/mcp"
PROTOCOL = "2025-06-18"
AGENT = "jarvis-command"

SEARCH, SCHEMAS, RUN, MANAGE = "COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL", "COMPOSIO_MANAGE_CONNECTIONS"
TIERS = {"read": (SEARCH, SCHEMAS, RUN), "act": (SEARCH, SCHEMAS, RUN), "connect": (SEARCH, MANAGE)}
# What the helper may hand on, tool by tool. Anything else it sends is dropped (and the workbench copy is always off).
PASSED = {SEARCH: ("queries", "session", "search_strategy", "model"), SCHEMAS: ("tool_slugs", "include", "session_id"),
          RUN: ("tools", "session_id", "current_step", "current_step_metric", "thought"), MANAGE: ("toolkits", "session_id")}
CONNECTING = ("add", "list", "remove")          # what may be done with an account in a connect request (not "rename")

# The words in an app tool's name ("GMAIL_FETCH_EMAILS" -> FETCH, EMAILS) that say it reads, and those that say it may change
# something. A name with any changing word, or with no reading word, is not run in a lookup: refusing a read only costs the
# owner a question, letting a change through could send their mail. (Plurals are other words: LIST_DRAFTS reads.)
READ_WORDS = frozenset("GET LIST FETCH SEARCH FIND READ RETRIEVE LOOKUP VIEW SHOW DESCRIBE COUNT CHECK DOWNLOAD EXPORT".split())   # (not QUERY: it can carry SQL)
CHANGE_WORDS = frozenset((
    "SEND CREATE UPDATE DELETE REMOVE ADD INSERT SET PUT POST PATCH REPLY FORWARD DRAFT MOVE COPY TRASH UNTRASH ARCHIVE MODIFY "
    "EDIT WRITE UPLOAD IMPORT SHARE INVITE MERGE CLOSE OPEN ASSIGN STAR PIN LIKE FOLLOW COMMENT REACT LABEL MARK RENAME RUN "
    "EXECUTE EXEC SQL GRAPHQL BATCH TRIGGER START STOP CANCEL APPROVE PUBLISH SUBSCRIBE WATCH PROXY REQUEST CALL INVOKE WEBHOOK "
    "DUPLICATE CLEAR EMPTY RESTORE ENABLE DISABLE GENERATE ACCEPT DECLINE RSVP PAY REFUND TRANSFER REVOKE DISMISS LOCK SYNC SUBMIT "
    "RESOLVE REJECT GRANT MUTE BLOCK JOIN LEAVE LINK ATTACH DETACH REPLACE UPSERT APPEND CONVERT COMPLETE SCHEDULE PURGE DROP "
    "DEPLOY PUSH ACTIVATE VERIFY RESET REVERT TOGGLE").split())
# Apps whose every tool name was checked one by one against these rules (tests/test_composio_gate.py): in their names a reading
# word may stand anywhere, these pairs are one word, and these whole names read. In any other app's names the first word must
# be a reading word, so that "LOCK_AN_ISSUE_LIST" is not taken for a list.
CHECKED = {"GMAIL": {"SEND_AS": "SENDAS"}, "GOOGLE_CLASSROOM": {"ADD_ON": "ADDON"}}
CHECKED_READS = {"GMAIL": frozenset({"GET_DRAFT", "GET_LABEL", "WHO_AM_I"})}
NEEDS_YES = "Not done: this may change something, and that needs the owner's yes first."
_CONNECTED = re.compile(r"connected the apps:\s*([a-z0-9_\-]+(?:\s*,\s*[a-z0-9_\-]+)*)", re.I)


class GateError(ValueError):
    """Composio could not be reached, or would not take the key. (Its words never carry the key.)"""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A request that carries the key goes to one address only: urllib would otherwise send the key on to wherever a
    redirect points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def opener():
    return urllib.request.build_opener(_NoRedirect())


# ---------------------------------------------------------------------- talking to Composio's server
class Connect:
    """A small client for Composio's Connect server (MCP over HTTP), with a ck_ key."""

    def __init__(self, key: str, open_with=None, timeout: float = 60.0):
        self.key, self.open_with, self.timeout = key, open_with or opener(), timeout
        self.session, self.number, self.ready = "", 0, False
        register_secret(key)

    def _post(self, method: str, params: dict | None = None, notice: bool = False) -> dict:
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notice:
            self.number += 1
            body["id"] = self.number
        headers = {"x-consumer-api-key": self.key, "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": AGENT}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.ready:
            headers["MCP-Protocol-Version"] = PROTOCOL
        request = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with self.open_with.open(request, timeout=self.timeout) as response:
                raw = response.read(4_000_000).decode("utf-8", "replace")
                given = getattr(response, "headers", None)
                session = given.get("Mcp-Session-Id") if given is not None else None
                if session and re.fullmatch(r"[\x21-\x7e]{1,200}", session):
                    self.session = session
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise GateError("Composio did not accept the key.", error.code) from None
            if error.code == 429:
                raise GateError("Composio has reached its limit for now. Try again in a little while.", 429) from None
            if 300 <= error.code < 400:
                raise GateError("Composio answered from another address, so the key was not sent there.", error.code) from None
            raise GateError(f"Composio could not do that (it answered {error.code}).", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GateError("Composio could not be reached. Check the internet connection.") from None
        if notice:
            return {}
        for message in _messages(raw):
            if message.get("id") == body["id"]:
                if isinstance(message.get("error"), dict):
                    raise GateError("Composio could not do that: " + redact(str(message["error"].get("message") or ""))[:200])
                result = message.get("result")
                return result if isinstance(result, dict) else {}
        raise GateError("Composio gave no answer that could be read.")

    def start(self) -> None:
        if self.ready:
            return
        self._post("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": AGENT, "version": "1"}})
        self.ready = True
        self._post("notifications/initialized", notice=True)

    def tools(self) -> list[dict]:
        self.start()
        found = self._post("tools/list", {}).get("tools")
        return [tool for tool in found if isinstance(tool, dict) and isinstance(tool.get("name"), str)] if isinstance(found, list) else []

    def call(self, name: str, arguments: dict) -> dict:
        self.start()
        return self._post("tools/call", {"name": name, "arguments": arguments})


def _messages(raw: str) -> list[dict]:
    """The JSON-RPC messages in an answer: one JSON body, or an event stream with one in each "data:" line."""
    text = raw.strip()
    found = []
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        found = data if isinstance(data, list) else [data]
    else:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    found.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    return [message for message in found if isinstance(message, dict)]


def check(key: str, open_with=None) -> list[dict]:
    """Is this a working ck_ key? Composio's server is asked what it offers: the key is good when it answers with its
    search tool and the tool that runs tools. Returns what it offers."""
    tools = Connect(key, open_with).tools()
    names = {tool["name"] for tool in tools}
    if SEARCH not in names or RUN not in names:
        raise GateError("Composio answered, but not as expected: its tools for apps are missing.")
    return tools


def connected_in(tools: list[dict]) -> list[str] | None:
    """The apps the owner has connected, as Composio's server says them in its search tool's description, or None when
    it does not say (then nothing is looked up: an unknown list is never taken as "everything")."""
    search = next((tool for tool in tools if tool.get("name") == SEARCH), None)
    found = _CONNECTED.search(str((search or {}).get("description") or ""))
    if not found:
        return None
    apps = sorted({app.strip().lower() for app in found.group(1).split(",") if app.strip()})
    return [app for app in apps if re.fullmatch(r"[a-z0-9_\-]{1,60}", app)]


# ---------------------------------------------------------------------- what may pass
def refusal(slug, tier: str, apps: list[str]) -> str:
    """Why an app tool may not be run in this kind of request, or "" when it may."""
    if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_]{3,120}", slug):
        return "That is not a tool's name."
    slug = slug.upper()
    if slug.startswith("COMPOSIO_"):
        return "Composio's own tools are not run this way."
    app = max((app for app in apps if slug.startswith(app.upper().replace("-", "_") + "_")), key=len, default="")
    if not app:
        return "That app is not connected, so nothing was done in it."
    if tier == "act":
        return ""
    prefix = app.upper().replace("-", "_")
    rest = slug[len(prefix) + 1:]
    if rest in CHECKED_READS.get(prefix, ()):
        return ""
    rest = "_" + rest + "_"
    for pair, one in CHECKED.get(prefix, {}).items():
        rest = rest.replace("_" + pair + "_", "_" + one + "_")
    words = [word for word in rest.split("_") if word]
    if not words or any(_changes(word) for word in words):
        return NEEDS_YES
    if not (words[0] in READ_WORDS or (prefix in CHECKED and set(words) & READ_WORDS)):
        return NEEDS_YES
    return ""


def _changes(word: str) -> bool:
    """Does this word of a tool's name say it may change something (UNFOLLOW, REREQUEST and DEACTIVATE count too)?"""
    if word in CHANGE_WORDS:
        return True
    return word not in READ_WORDS and any(word.startswith(part) and word[len(part):] in CHANGE_WORDS for part in ("UN", "RE", "DE"))


def passed(name: str, arguments, tier: str, apps: list[str]) -> tuple[dict | None, str]:
    """(what is handed on to Composio, or None, and why not)."""
    if name not in TIERS.get(tier, ()):
        return None, "That tool is not available here."
    if not isinstance(arguments, dict):
        return None, "Those details do not fit this tool."
    kept = {key: value for key, value in arguments.items() if key in PASSED[name]}
    if name == RUN:
        tools = kept.get("tools")
        if not isinstance(tools, list) or not 1 <= len(tools) <= 50:
            return None, "Those details do not fit this tool."
        clean = []
        for item in tools:
            if not isinstance(item, dict) or not isinstance(item.get("arguments", {}), dict):
                return None, "Those details do not fit this tool."
            why = refusal(item.get("tool_slug"), tier, apps)
            if why:
                return None, why + " (" + redact(str(item.get("tool_slug")))[:80] + ")"
            one = {"tool_slug": item["tool_slug"].upper(), "arguments": item.get("arguments") or {}}
            if isinstance(item.get("account"), str):
                one["account"] = item["account"][:200]
            clean.append(one)
        kept["tools"] = clean
        kept["sync_response_to_workbench"] = False
    elif name == MANAGE:
        asked = kept.get("toolkits")
        if not isinstance(asked, list) or not asked:
            return None, "Those details do not fit this tool."
        clean = []
        for item in asked:
            if isinstance(item, str):                      # (an older form of the tool: names only, each checked or connected)
                item = {"name": item}
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                return None, "Those details do not fit this tool."
            action = item.get("action", "add")
            if action not in CONNECTING:
                return None, "Only connecting, listing and removing accounts is done here."
            clean.append({**{key: item[key] for key in ("name", "account_id", "alias") if key in item}, "action": action})   # (always said)
        kept["toolkits"] = clean
    return kept, ""


# ---------------------------------------------------------------------- the gate itself (an MCP server on stdin/stdout)
MOST_CALLS = 25                 # tool calls one request may make through the gate
TOO_MANY = "This request has used as many lookups as it may. Answer with what you have found."
_MARKER = re.compile(r"accounts-[0-9a-f]{8,32}\.started")


class Gate:
    def __init__(self, tier: str, apps: list[str], connect: Connect, marker: Path | None = None):
        self.tier, self.apps, self.connect, self.offered = tier, apps, connect, None
        self.marker, self.calls = marker, 0

    def _begun(self) -> None:
        """Leave word that something was handed on that may change the owner's accounts: then no other helper does this
        request again after a usage limit (it might do the same thing twice)."""
        if self.marker is not None and self.tier != "read":
            try:
                self.marker.touch()
            except OSError:
                pass

    def handle(self, message: dict) -> dict | None:
        method, ident = message.get("method"), message.get("id")
        try:
            if method == "initialize":
                result = {"protocolVersion": (message.get("params") or {}).get("protocolVersion", PROTOCOL),
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "accounts", "version": "1.0"}}
            elif method == "tools/list":
                if self.offered is None:
                    self.offered = [tool for tool in self.connect.tools() if tool["name"] in TIERS[self.tier]]
                result = {"tools": self.offered}
            elif method == "tools/call":
                params = message.get("params") or {}
                self.calls += 1
                kept, why = (None, TOO_MANY) if self.calls > MOST_CALLS else passed(params.get("name"), params.get("arguments"), self.tier, self.apps)
                if kept is not None and params.get("name") in (RUN, MANAGE):
                    self._begun()
                result = self.connect.call(params["name"], kept) if kept is not None else {"content": [{"type": "text", "text": why}], "isError": True}
            elif method == "ping":
                result = {}
            elif ident is None:
                return None
            else:
                return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Method not found"}}
        except GateError as error:
            if method != "tools/call":
                return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32000, "message": str(error)}} if ident is not None else None
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        return {"jsonrpc": "2.0", "id": ident, "result": result} if ident is not None else None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tier = argv[0] if argv else ""
    apps = [app for app in (argv[1] if len(argv) > 1 else "").split(",") if re.fullmatch(r"[a-z0-9_\-]{1,60}", app)]
    given = os.environ.pop("JCC_COMPOSIO_KEY", "")         # (taken out at once: nothing else here ever sees it)
    if tier not in TIERS:
        return 2
    from jcc import secrets
    key = secrets.get("composio") or given
    if not key.startswith("ck_"):
        return 2
    marker = Path(argv[2]) if len(argv) > 2 and _MARKER.fullmatch(Path(argv[2]).name) else None
    gate = Gate(tier, apps, Connect(key), marker)
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    for raw in stdin:
        try:
            message = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        reply = gate.handle(message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply).encode("utf-8") + b"\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
