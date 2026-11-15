"""Connectors added without editing a file (jcc/connectors.py): pasted as a link, a command or setup JSON, or brought in from
Claude; their secrets kept in the key store with placeholders in connectors.json; tested by starting them."""
import json
import os
import sys
import tempfile
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jcc import connectors, secrets
from jcc.jobs import scrub_env
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

PROBE = textwrap.dedent('''
    import json, os, sys
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        if msg["method"] == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "probe", "version": "1"}}
        else:
            ok = os.environ.get("PROBE_TOKEN") == "tok-1234567890" and sys.argv[1:] == ["--api-key", "argsecret-98765"]
            res = {"tools": [{"name": "ping" if ok else "wrong_secret", "inputSchema": {"type": "object"}}]}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}) + "\\n"); sys.stdout.flush()
''')


class Case(EngineTestCase):
    def setUp(self):
        super().setUp()
        from jcc import config
        self.cfg = config.load()

    def saved(self):
        return (self.cfg.state_dir / "connectors.json").read_text("utf-8")


class Pasting(Case):
    def test_a_link_a_command_and_setup_json_are_all_understood(self):
        link = connectors.parse("https://mcp.linear.app/mcp")
        self.assertEqual(link, {"linear": {"type": "http", "url": "https://mcp.linear.app/mcp"}})
        command = connectors.parse("npx -y @modelcontextprotocol/server-github")
        self.assertEqual(list(command), ["github"])
        self.assertEqual(command["github"], {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]})
        setup = connectors.parse('{"mcpServers": {"notes": {"command": "uvx", "args": ["notes-mcp"]}, "db": {"type": "http", "url": "https://db.example.com/mcp"}}}')
        self.assertEqual(sorted(setup), ["db", "notes"])
        one = connectors.parse('{"command": "node", "args": ["server.js"]}', name="my-tool")
        self.assertEqual(list(one), ["my-tool"])

    def test_what_is_not_a_connector_is_said_plainly(self):
        for text, said in (("", "Paste"), ("{not json", "not valid JSON"), ("http://example.com/mcp", "https://"), ('{"x": 1}', "No connector")):
            with self.assertRaisesRegex(connectors.ConnectorError, said):
                connectors.parse(text)
        with self.assertRaisesRegex(connectors.ConnectorError, "jarvis"):
            connectors.parse("npx something", name="jarvis")


class Secrets(Case):
    def test_a_links_token_goes_to_the_key_store_and_the_file_keeps_a_placeholder(self):
        added = connectors.add(self.cfg, "https://api.githubcopilot.com/mcp/", name="github", token="ghp_abcdefghijklmnopqrstuvwxyz0123")
        self.assertEqual(added[0]["secrets"], 1)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123", self.saved())
        entry = json.loads(self.saved())["mcpServers"]["github"]
        self.assertRegex(entry["headers"]["Authorization"], r"^\$\{JCC_CONNECTOR_GITHUB_AUTHORIZATION\}$")
        self.assertEqual(connectors.secret_env(self.cfg), {"JCC_CONNECTOR_GITHUB_AUTHORIZATION": "Bearer ghp_abcdefghijklmnopqrstuvwxyz0123"})
        self.assertTrue(connectors.remove(self.cfg, "github"))
        self.assertIsNone(secrets._cred_read("c-JCC_CONNECTOR_GITHUB_AUTHORIZATION"), "its key is deleted with it")
        self.assertEqual(connectors.secret_env(self.cfg), {})

    def test_keys_in_environment_values_and_arguments_are_found_and_the_rest_left_alone(self):
        connectors.add(self.cfg, json.dumps({"mcpServers": {"tool": {"command": "node", "args": ["server.js", "--api-key", "argsecret-98765", "--token=tok-abcdef",
                                                                                                "--port", "8080"],
                                                                      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_abcdefghijklmnopqrstuvwxyz0123", "LOG_LEVEL": "debug",
                                                                              "HOME_DIR": "C:\\\\Users\\\\ann"}}}}))
        text = self.saved()
        for secret in ("argsecret-98765", "tok-abcdef", "ghp_abcdefghijklmnopqrstuvwxyz0123"):
            self.assertNotIn(secret, text)
        entry = json.loads(text)["mcpServers"]["tool"]
        self.assertEqual(entry["env"]["LOG_LEVEL"], "debug")
        self.assertEqual(entry["args"][0], "server.js")
        self.assertEqual(entry["args"][4:], ["--port", "8080"])
        self.assertEqual(len(connectors.secret_env(self.cfg)), 3)
        shown = connectors.listing(self.cfg)[0]
        self.assertIn("•••", shown["where"])
        self.assertNotIn("argsecret", shown["where"])

    def test_the_secrets_never_reach_what_the_assistant_runs(self):
        env = {"JCC_CONNECTOR_X_TOKEN": "s", "PATH": "p"}
        connectors.strip_env(env)
        self.assertEqual(env, {"PATH": "p"})
        self.assertNotIn("JCC_CONNECTOR_X_TOKEN", scrub_env({"JCC_CONNECTOR_X_TOKEN": "s"}), "nor what coding jobs run")
        source = (Path(connectors.__file__).with_name("assistant.py")).read_text("utf-8")
        self.assertIn("env.update(connectors.secret_env(self.cfg))", source)
        self.assertIn("connectors.strip_env(os.environ)", Path(connectors.__file__).with_name("voice_tools.py").read_text("utf-8"))


class FromClaude(Case):
    def test_the_connectors_set_up_in_claude_are_offered_and_brought_in(self):
        folder = Path(tempfile.mkdtemp())
        desktop, code = folder / "claude_desktop_config.json", folder / ".claude.json"
        desktop.write_text(json.dumps({"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\\\notes"]},
                                                       "brave": {"command": "npx", "args": ["-y", "brave-search"], "env": {"BRAVE_API_KEY": "BSAabcdefghijklmnop123456789"}}}}), "utf-8")
        code.write_text(json.dumps({"mcpServers": {"linear": {"type": "http", "url": "https://mcp.linear.app/mcp"}}, "projects": {}}), "utf-8")
        files = [("Claude Desktop", desktop), ("Claude Code", code)]
        offered = connectors.in_claude(self.cfg, files)
        self.assertEqual(sorted((c["source"], c["name"], c["secret"]) for c in offered),
                         [("Claude Code", "linear", False), ("Claude Desktop", "brave", True), ("Claude Desktop", "filesystem", False)])
        connectors.bring_in(self.cfg, "Claude Desktop", ["brave"], files)
        self.assertNotIn("BSAabcdefghijklmnop123456789", self.saved())
        self.assertTrue(next(c for c in connectors.in_claude(self.cfg, files) if c["name"] == "brave")["there"])


class Testing(Case):
    def test_a_program_is_started_with_its_secrets_filled_in_and_its_tools_listed(self):
        script = Path(tempfile.mkdtemp()) / "probe.py"
        script.write_text(PROBE, "utf-8")
        connectors.add(self.cfg, json.dumps({"mcpServers": {"probe": {"command": sys.executable, "args": [str(script), "--api-key", "argsecret-98765"],
                                                                       "env": {"PROBE_TOKEN": "tok-1234567890"}}}}))
        self.assertNotIn("tok-1234567890", self.saved())
        self.assertEqual(connectors.test(self.cfg, "probe", timeout=30), {"ok": True, "tools": ["ping"], "problem": ""})

    def test_a_program_that_is_not_there_is_said_plainly(self):
        connectors.add(self.cfg, "no-such-program-xyz --serve", name="ghost")
        result = connectors.test(self.cfg, "ghost", timeout=5)
        self.assertFalse(result["ok"])
        self.assertRegex(result["problem"], "could not be started|stopped")

    def test_a_link_is_asked_for_its_tools(self):
        seen = {}

        class Server(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.setdefault("auth", self.headers.get("Authorization"))
                if self.headers.get("Authorization") != "Bearer tok-abcdef1234":
                    self.send_response(401); self.end_headers(); return
                if "id" not in message:
                    self.send_response(202); self.end_headers(); return
                result = {"tools": [{"name": "search"}, {"name": "create_issue"}]} if message["method"] == "tools/list" else {"protocolVersion": "2025-06-18"}
                body = ("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}) + "\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Mcp-Session-Id", "s1")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
            connectors.add(self.cfg, url, name="tracker", token="tok-abcdef1234")
            self.assertEqual(connectors.test(self.cfg, "tracker", timeout=10)["tools"], ["search", "create_issue"])
            connectors.add(self.cfg, url, name="nokey")
            self.assertRegex(connectors.test(self.cfg, "nokey", timeout=10)["problem"], "needs signing in")
        finally:
            httpd.shutdown()


class OverTheWire(GuiTestCase):
    def test_add_list_and_remove_from_the_window(self):
        status, got = self.req("POST", "/api/connectors", {"action": "add", "text": "https://api.githubcopilot.com/mcp/", "name": "github",
                                                            "token": "ghp_abcdefghijklmnopqrstuvwxyz0123"})
        self.assertEqual(status, 200, got)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123", json.dumps(got))
        self.assertEqual([c["name"] for c in got["connectors"]], ["github"])
        self.assertEqual(self.req("POST", "/api/connectors", {"action": "list"}, token=False)[0], 401)
        self.assertEqual(self.req("POST", "/api/connectors", {"action": "remove", "name": "github"})[1]["connectors"], [])
        self.assertEqual(self.req("POST", "/api/connectors", {"action": "add", "text": "{bad"})[0], 400)


class StaysAdded(Case):
    """A connector stays until its owner removes it."""

    def test_it_and_its_keys_are_still_there_after_a_restart_and_a_failed_test(self):
        connectors.add(self.cfg, "https://api.githubcopilot.com/mcp/", name="github", token="ghp_abcdefghijklmnopqrstuvwxyz0123")
        connectors.add(self.cfg, "no-such-program-xyz --serve", name="ghost")
        self.assertFalse(connectors.test(self.cfg, "ghost", timeout=5)["ok"])
        from jcc import config
        again = config.load()
        self.assertEqual(sorted(c["name"] for c in connectors.listing(again)), ["ghost", "github"])
        self.assertEqual(connectors.secret_env(again), {"JCC_CONNECTOR_GITHUB_AUTHORIZATION": "Bearer ghp_abcdefghijklmnopqrstuvwxyz0123"})


class OtherConnections(Case):
    """Email and online accounts count as connected while their key is kept: no failed check, and no missing internet,
    makes them look disconnected."""

    def test_mail_and_online_accounts_stay_connected_without_the_internet(self):
        import socket
        from unittest import mock
        from jcc import mailer, online
        secrets.store("mail", "app-password")
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.state_dir / "mail.json").write_text(json.dumps({"address": "ann@example.com", "host": "smtp.example.com"}), "utf-8")
        secrets.store("composio", "ak_test")
        with mock.patch.object(socket, "create_connection", side_effect=OSError("no internet")):
            self.assertTrue(online.connected(self.cfg))
            status = mailer.status(self.cfg)
        self.assertTrue(status["connected"], status)
