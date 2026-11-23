"""The gate that stands between the helper for online accounts and Composio when the owner's key starts with ck_
(jcc/composio_gate.py). A fake Composio Connect server throughout: nothing here reaches composio.dev."""
import io
import json
import unittest
import urllib.error

from jcc import composio_gate as gate

KEY = "ck_test_key_0123456789abcdef"
ALL = ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL", "COMPOSIO_MANAGE_CONNECTIONS",
       "COMPOSIO_WAIT_FOR_CONNECTIONS", "COMPOSIO_REMOTE_WORKBENCH", "COMPOSIO_REMOTE_BASH_TOOL", "COMPOSIO_PROXY_EXECUTE",
       "COMPOSIO_MANAGE_SKILL", "COMPOSIO_SEARCH_SKILLS", "COMPOSIO_USE_SKILL", "COMPOSIO_SUBMIT_FEEDBACK"]
NEVER = [name for name in ALL if name not in ("COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL",
                                              "COMPOSIO_MANAGE_CONNECTIONS")]


class Answer(io.BytesIO):
    def __init__(self, body: bytes, headers=None, status=200):
        super().__init__(body)
        self.headers, self.status = headers or {}, status

    def __enter__(self):
        return self

    def __exit__(self, *rest):
        self.close()


class FakeConnect:
    """Composio's Connect server: accepts one key, answers as an event stream (stream=True) or as plain JSON."""

    def __init__(self, stream=True, connected="github, gmail, google_classroom", redirect=False):
        self.seen, self.stream, self.connected, self.redirect = [], stream, connected, redirect

    def open(self, request, timeout=0):
        body = json.loads(request.data.decode())
        self.seen.append({"url": request.full_url, "key": request.headers.get("X-consumer-api-key"), "body": body,
                          "session": request.headers.get("Mcp-session-id")})
        if self.redirect:
            raise urllib.error.HTTPError(request.full_url, 302, "Found", {"Location": "https://elsewhere.example/mcp"}, io.BytesIO(b""))
        if request.headers.get("X-consumer-api-key") != KEY:
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"Invalid key ck_wrong_value"}'))
        if "id" not in body:
            return Answer(b"", status=202)
        method = body["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "composio"}}
        elif method == "tools/list":
            said = "Discover tools." + (f" - User has manually connected the apps: {self.connected}. Prefer these apps." if self.connected else "")
            result = {"tools": [{"name": name, "description": said if name == "COMPOSIO_SEARCH_TOOLS" else name, "inputSchema": {"type": "object"}}
                                for name in ALL]}
        else:
            result = {"content": [{"type": "text", "text": json.dumps({"ran": body["params"]["name"], "with": body["params"]["arguments"]})}]}
        message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if self.stream:
            return Answer(("event: message\ndata: " + json.dumps(message) + "\n\n").encode(), {"Mcp-Session-Id": "s-1", "Content-Type": "text/event-stream"})
        return Answer(json.dumps(message).encode(), {"Mcp-Session-Id": "s-1", "Content-Type": "application/json"})

    def calls(self):
        return [s["body"]["params"] for s in self.seen if s["body"].get("method") == "tools/call"]


def ask(g, name, arguments, ident=9):
    return g.handle({"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": {"name": name, "arguments": arguments}})["result"]


def run(*slugs):
    return {"tools": [{"tool_slug": slug, "arguments": {}} for slug in slugs], "sync_response_to_workbench": False}


class TestTheConnection(unittest.TestCase):
    def test_a_good_key_is_told_apart_from_a_bad_one_without_the_key_in_the_words(self):
        for stream in (True, False):
            server = FakeConnect(stream=stream)
            tools = gate.check(KEY, server)
            self.assertIn("COMPOSIO_MULTI_EXECUTE_TOOL", [tool["name"] for tool in tools])
            self.assertEqual({s["url"] for s in server.seen}, {gate.URL})
            self.assertEqual(server.seen[-1]["session"], "s-1", "the session Composio gave is carried on")
        with self.assertRaises(gate.GateError) as refused:
            gate.check("ck_wrong_key_0123456789abcdef", FakeConnect())
        self.assertEqual(refused.exception.code, 401)
        self.assertNotIn("ck_wrong", str(refused.exception))

    def test_no_redirect_is_followed_with_the_key(self):
        server = FakeConnect(redirect=True)
        with self.assertRaises(gate.GateError):
            gate.check(KEY, server)
        self.assertEqual(len(server.seen), 1, "nothing is sent to where the redirect points")
        handler = gate._NoRedirect()
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(type("R", (), {"full_url": gate.URL})(), None, 302, "Found", {}, "https://elsewhere.example/")

    def test_the_connected_apps_are_read_from_what_composio_says_and_unknown_is_never_everything(self):
        tools = gate.check(KEY, FakeConnect())
        self.assertEqual(gate.connected_in(tools), ["github", "gmail", "google_classroom"])
        self.assertIsNone(gate.connected_in(gate.check(KEY, FakeConnect(connected=""))))


class TestWhatPasses(unittest.TestCase):
    def setUp(self):
        self.server = FakeConnect()
        self.apps = ["github", "gmail", "google_classroom"]

    def gate(self, tier):
        return gate.Gate(tier, self.apps, gate.Connect(KEY, self.server))

    def test_each_kind_of_request_sees_only_its_tools(self):
        for tier, expected in (("read", ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL"]),
                               ("act", ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL"]),
                               ("connect", ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_MANAGE_CONNECTIONS"])):
            listed = self.gate(tier).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
            self.assertEqual([tool["name"] for tool in listed], expected, tier)

    def test_the_tools_never_offered_are_refused_without_asking_composio(self):
        for tier in ("read", "act", "connect"):
            g = self.gate(tier)
            for name in NEVER:
                self.assertTrue(ask(g, name, {"command": "curl https://evil.example"})["isError"], (tier, name))
        self.assertEqual(self.server.calls(), [])

    def test_a_lookup_runs_only_tools_that_read_in_connected_apps(self):
        g = self.gate("read")
        for slug in ("GMAIL_FETCH_EMAILS", "GITHUB_LIST_REPOSITORY_ISSUES", "GOOGLE_CLASSROOM_LIST_COURSES", "GMAIL_LIST_DRAFTS", "GMAIL_LIST_LABELS",
                     "gmail_fetch_emails"):
            self.assertFalse(ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run(slug)).get("isError"), slug)
        for slug in ("GMAIL_SEND_EMAIL", "GMAIL_X_GET_OR_CREATE_Y", "COMPOSIO_REMOTE_BASH_TOOL", "SLACK_FETCH_HISTORY", "SUPABASE_RUN_SQL_QUERY",
                     "GMAIL_DELETE_MESSAGE", "GITHUB_CREATE_AN_ISSUE", "GMAIL_MOVE_TO_TRASH", "GMAIL_THREADS", "GMAIL_FETCH EMAILS", "GMAIL_REPLY_TO_THREAD"):
            result = ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run(slug))
            self.assertTrue(result["isError"], slug)
        self.assertIn("needs the owner's yes", ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run("GMAIL_SEND_EMAIL"))["content"][0]["text"])
        ran = [tool["tool_slug"] for call in self.server.calls() for tool in call["arguments"]["tools"]]
        self.assertNotIn("GMAIL_SEND_EMAIL", ran)
        self.assertIn("GMAIL_FETCH_EMAILS", ran, "the name is passed on in capitals")

    def test_one_refused_tool_in_a_batch_refuses_the_batch(self):
        g = self.gate("read")
        before = len(self.server.calls())
        self.assertTrue(ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run(*(["GMAIL_FETCH_EMAILS"] * 49 + ["GMAIL_SEND_EMAIL"])))["isError"])
        self.assertEqual(len(self.server.calls()), before)

    def test_only_what_the_tool_takes_is_handed_on_and_the_workbench_copy_is_off(self):
        g = self.gate("read")
        ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_FETCH_EMAILS", "arguments": {"max_results": 3}, "extra": 1}],
                                              "sync_response_to_workbench": True, "workbench_code": "import os", "session_id": "abc"})
        sent = self.server.calls()[-1]["arguments"]
        self.assertFalse(sent["sync_response_to_workbench"])
        self.assertNotIn("workbench_code", sent)
        self.assertEqual(sent["tools"], [{"tool_slug": "GMAIL_FETCH_EMAILS", "arguments": {"max_results": 3}}])
        self.assertEqual(sent["session_id"], "abc")

    def test_a_change_the_owner_agreed_to_is_done_in_connected_apps_only(self):
        g = self.gate("act")
        self.assertFalse(ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run("GMAIL_SEND_EMAIL")).get("isError"))
        self.assertTrue(ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run("SLACK_SEND_MESSAGE"))["isError"])
        self.assertTrue(ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run("COMPOSIO_REMOTE_WORKBENCH"))["isError"])
        self.assertTrue(ask(g, "COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": [{"name": "gmail", "action": "remove"}]})["isError"],
                        "a change in an app does not connect or remove accounts")

    def test_connecting_may_add_list_and_remove_accounts_and_nothing_else(self):
        g = self.gate("connect")
        for action in ("add", "list", "remove"):
            self.assertFalse(ask(g, "COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": [{"name": "slack", "action": action}]}).get("isError"), action)
        self.assertFalse(ask(g, "COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": ["slack"], "reinitiate_all": True}).get("isError"))
        self.assertNotIn("reinitiate_all", self.server.calls()[-1]["arguments"])
        self.assertTrue(ask(g, "COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": [{"name": "gmail", "action": "rename", "alias": "x"}]})["isError"])
        self.assertTrue(ask(g, "COMPOSIO_MULTI_EXECUTE_TOOL", run("GMAIL_FETCH_EMAILS"))["isError"])

    def test_composio_trouble_comes_back_as_words_not_a_crash(self):
        g = gate.Gate("read", self.apps, gate.Connect("ck_wrong_key_0123456789abcdef", self.server))
        result = ask(g, "COMPOSIO_SEARCH_TOOLS", {"queries": [{"use_case": "find emails"}]})
        self.assertTrue(result["isError"])
        self.assertIn("did not accept the key", result["content"][0]["text"])
        listed = g.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("error", listed)

    def test_the_kind_and_the_apps_come_from_jarvis_not_the_helper(self):
        self.assertEqual(gate.main(["everything"]), 2)


if __name__ == "__main__":
    unittest.main()


class TheLookupRulesHoldForToolsNobodyListed(unittest.TestCase):
    """Names shaped like a change must not pass as a lookup in apps whose tools were not checked one by one."""

    def refused(self, slug, apps):
        from jcc import composio_gate
        return composio_gate.refusal(slug, "read", apps) == composio_gate.NEEDS_YES

    def test_change_shaped_names_are_not_lookups(self):
        for slug, app in (("TWITTER_UNFOLLOW_A_LIST", "twitter"), ("GITHUB_REREQUEST_A_CHECK_SUITE", "github"),
                          ("GITHUB_LOCK_AN_ISSUE_LIST", "github"), ("SLACK_UNARCHIVE_CHANNEL_LIST", "slack"),
                          ("GITHUB_SUBMIT_REVIEW_CHECK", "github"), ("SUPABASE_QUERY", "supabase"),
                          ("NOTION_QUERY_DATABASE", "notion"), ("PAGERDUTY_LIST_ADD_ON_CALL", "pagerduty"),
                          ("GITHUB_GET_DRAFT", "github"), ("SLACK_LIST_SEND_AS", "slack")):
            self.assertTrue(self.refused(slug, [app]), slug)

    def test_the_checked_apps_reads_pass(self):
        apps = ["gmail", "google_classroom"]
        for slug in ("GMAIL_GET_DRAFT", "GMAIL_GET_LABEL", "GMAIL_LIST_SEND_AS", "GMAIL_SETTINGS_SEND_AS_GET", "GMAIL_WHO_AM_I",
                     "GMAIL_SETTINGS_GET_IMAP", "GMAIL_FETCH_EMAILS", "GOOGLE_CLASSROOM_COURSES_LIST",
                     "GOOGLE_CLASSROOM_COURSES_ANNOUNCEMENTS_GET_ADD_ON_CONTEXT", "GOOGLE_CLASSROOM_COURSES_POSTS_ADD_ON_ATTACHMENTS_LIST",
                     "GOOGLE_CLASSROOM_COURSES_ANNOUNCES_ADD_ON_ATTACHS_GET"):
            self.assertFalse(self.refused(slug, apps), slug)
        for slug in ("GMAIL_SEND_EMAIL", "GMAIL_PATCH_SEND_AS", "GMAIL_CREATE_EMAIL_DRAFT", "GMAIL_UNTRASH_MESSAGE",
                     "GOOGLE_CLASSROOM_COURSES_COURSE_WORK_ADD_ON_ATTACHS_DELETE", "GOOGLE_CLASSROOM_TURN_IN_STUDENT_SUBMISSION",
                     "GOOGLE_CLASSROOM_COURSE_WORK_STUDENT_SUBMISSIONS_RECLAIM"):
            self.assertTrue(self.refused(slug, apps), slug)

    def test_an_account_action_is_always_said(self):
        from jcc import composio_gate
        kept, why = composio_gate.passed(composio_gate.MANAGE, {"toolkits": ["gmail"]}, "connect", [])
        self.assertEqual(why, "")
        self.assertEqual(kept["toolkits"], [{"name": "gmail", "action": "add"}])
