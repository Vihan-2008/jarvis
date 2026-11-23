"""ChatGPT as JARVIS's brain, through Codex and the owner's ChatGPT sign-in (jcc/codex_brain.py), and the accounts that
decide who answers (jcc/accounts.py): a Claude free plan is told apart and left out. A fake Codex process throughout:
nothing here starts the real Codex or Claude, or reads the real sign-ins."""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jcc import accounts, agents, assistant, codex_brain
from tests.test_brain import LIMIT, BrainCase
from tests.test_assistant_voice import AssistantCase


class Inbox(io.StringIO):
    """A process's stdin that keeps what was written to it once it is closed."""
    kept = ""

    def close(self):
        self.kept = self.getvalue()
        super().close()


class FakeCodex:
    """`codex exec --json`: the request arrives on stdin, the events go out on stdout as JSON lines."""

    def __init__(self, events, stderr="", code=0):
        self.stdin, self.stdout, self.stderr = Inbox(), io.StringIO("".join(json.dumps(e) + "\n" for e in events)), io.StringIO(stderr)
        self.code, self.pid, self.argv, self.kw = code, 0, [], {}

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        pass


def answer(text, tool=None, usage=(5000, 4000, 30)):
    events = [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"}]
    if tool:
        events.append({"type": "item.started", "item": {"id": "i0", "type": "mcp_tool_call", "server": "jarvis", "tool": tool[0], "arguments": tool[1], "status": "in_progress"}})
        events.append({"type": "item.completed", "item": {"id": "i0", "type": "mcp_tool_call", "server": "jarvis", "tool": tool[0], "status": "completed"}})
    events.append({"type": "item.completed", "item": {"id": "i1", "type": "error", "message": "Codex is ignoring a setting it does not know"}})
    events.append({"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": text}})
    events.append({"type": "turn.completed", "usage": {"input_tokens": usage[0], "cached_input_tokens": usage[1], "output_tokens": usage[2]}})
    return events


class Codexes:
    """Hands out a FakeCodex for each request, from a list of scripts, and keeps them."""

    def __init__(self, *scripts):
        self.scripts, self.made = list(scripts), []

    def __call__(self, argv, **kw):
        proc = FakeCodex(*self.scripts.pop(0)) if self.scripts else FakeCodex(answer("Okay."))
        proc.argv, proc.kw = argv, kw
        self.made.append(proc)
        return proc


class TestTheCommand(unittest.TestCase):
    def test_codex_runs_as_a_talker_with_jarvis_tools_and_nothing_of_its_own(self):
        argv = codex_brain.command("codex.exe", Path("C:/state/assistant/codex-1.md"), Path("C:/state/assistant"), python="python.exe")
        line = " ".join(argv)
        for part in ("exec --json --ephemeral --ignore-user-config --skip-git-repo-check -s read-only", "features.shell_tool=false",
                     "features.computer_use=false", "features.plugins=false", 'approval_policy="never"', 'web_search="live"',
                     'mcp_servers.jarvis.default_tools_approval_mode="approve"', "include_environment_context=false"):
            self.assertIn(part, line)
        self.assertIn('mcp_servers.jarvis.args=["-m", "jcc.voice_tools"]', argv)
        self.assertEqual(argv[-1], "-", "the request goes in on stdin, never on the command line")
        self.assertNotIn("-m", argv, "the plan's own model unless one is picked")
        self.assertEqual(codex_brain.command("codex.exe", Path("i.md"), Path("."), "gpt-5.5", "python.exe")[-3:], ["-m", "gpt-5.5", "-"])
        self.assertIn("JCC_VOICE_KEY", line, "the tools helper's key is passed by name, through the environment")


class TestTheSession(AssistantCase):
    def session(self, codexes, **kw):
        return codex_brain.CodexSession(self.cfg, "default", "You are JARVIS.", "abc123", 1234, "secret-helper-key", True, exe="codex.exe", popen=codexes, **kw)

    def test_tools_and_words_are_reported_like_claudes_and_the_talk_is_handed_back(self):
        codexes = Codexes((answer("Opened it.", ("open_app", {"name": "Notepad"})),), (answer("You asked me to open Notepad."),))
        session = self.session(codexes)
        events = list(session.events("[typed] open notepad"))
        starts = [e["event"] for e in events if e.get("type") == "stream_event" and e["event"]["type"] == "content_block_start"]
        self.assertEqual(starts[0]["content_block"], {"type": "tool_use", "name": "mcp__jarvis__open_app"})
        deltas = [e["event"]["delta"] for e in events if e.get("type") == "stream_event" and e["event"]["type"] == "content_block_delta"]
        self.assertEqual(json.loads(deltas[0]["partial_json"]), {"name": "Notepad"})
        self.assertEqual(deltas[-1], {"type": "text_delta", "text": "Opened it."})
        self.assertEqual(events[-1], {"type": "result", "is_error": False, "result": "Opened it.", "usage": {"input": 5000, "cached": 4000, "output": 30}})
        first = codexes.made[0]
        self.assertEqual(first.stdin.kept, "[typed] open notepad")
        self.assertNotIn("secret-helper-key", " ".join(first.argv), "the key is never on a command line")
        self.assertEqual(first.kw["env"]["JCC_VOICE_KEY"], "secret-helper-key")
        self.assertEqual(Path(session.instructions).read_text("utf-8"), "You are JARVIS.")
        # Codex starts afresh each time: the talk so far is handed back with the next request.
        list(session.events("[typed] what did I ask?"))
        self.assertIn("User: [typed] open notepad\nYou: Opened it.", codexes.made[1].stdin.kept)
        self.assertTrue(codexes.made[1].stdin.kept.endswith("Now:\n[typed] what did I ask?"))
        session.close()
        self.assertFalse(Path(session.instructions).exists(), "its instructions file goes with it")

    def test_a_missing_sign_in_is_said_plainly_and_brings_in_another_brain(self):
        failed = [{"type": "turn.failed", "error": {"message": "Not logged in. Please run codex login."}}]
        session = self.session(Codexes((failed,)))
        result = list(session.events("hello"))[-1]
        self.assertTrue(result["is_error"])
        self.assertIn("ChatGPT is not signed in", result["result"])
        self.assertTrue(assistant.TROUBLE.search(result["result"]), "another brain is asked instead")

    def test_a_used_up_chatgpt_plan_is_a_limit(self):
        failed = [{"type": "error", "message": "You've hit your usage limit. Upgrade to Plus to continue using Codex, or try again at 5:23 PM."}]
        result = list(self.session(Codexes((failed,))).events("hello"))[-1]
        self.assertTrue(result["is_error"] and assistant.is_limit(result["result"]))

    def _slow(self, events, pauses):
        """A Codex that prints its events slowly (pauses[i] seconds before event i) and stops when it is stopped."""
        proc = FakeCodex([])
        proc.code, proc.killed = None, False

        def lines():
            for event, pause in zip(events, pauses):
                end = time.monotonic() + pause
                while time.monotonic() < end:
                    if proc.killed:
                        return
                    time.sleep(0.01)
                yield json.dumps(event) + "\n"
            proc.code = 0
        proc.stdout = lines()
        return proc

    def _run(self, proc, quiet):
        session = self.session(lambda argv, **kw: proc)
        def kill(_self=None):
            proc.killed, proc.code = True, 1
        with mock.patch.object(codex_brain, "QUIET", quiet), mock.patch.object(codex_brain, "TOOL_QUIET", quiet), \
             mock.patch.object(codex_brain.CodexSession, "_kill", kill), \
             mock.patch.object(codex_brain, "LOOK", 0.02):
            return list(session.events("open notepad, then calculator, then paint"))[-1]

    def test_a_request_of_many_steps_is_not_cut_off_between_them(self):
        # Each step comes well inside the quiet limit, but the whole request takes several times longer than it.
        steps = answer("Opened all three.", ("open_app", {"name": "Notepad"}))
        result = self._run(self._slow(steps, [0.15] * len(steps)), quiet=0.4)
        self.assertFalse(result["is_error"], result)
        self.assertEqual(result["result"], "Opened all three.")

    def test_a_codex_that_goes_quiet_is_stopped_and_says_so(self):
        steps = answer("never said")
        result = self._run(self._slow(steps, [0.0, 0.0, 5.0] + [0.0] * (len(steps) - 3)), quiet=0.3)
        self.assertTrue(result["is_error"])
        self.assertIn("stopped responding", result["result"])

    def test_without_codex_it_cannot_start(self):
        with mock.patch.object(agents, "resolve_command", lambda name: None):
            with self.assertRaisesRegex(ValueError, "Codex is not installed"):
                codex_brain.CodexSession(self.cfg, "default", "x", "id", 1, "k", True)


class TestWhoAnswers(BrainCase):
    def with_accounts(self, agent, claude, chatgpt, *scripts):
        agent.brains = lambda: {"claude": claude, "chatgpt": chatgpt}
        self.codexes = Codexes(*scripts)
        agent.codex_with = {"exe": "codex.exe", "popen": self.codexes}
        return agent

    def test_chatgpt_answers_when_claude_is_on_its_free_plan(self):
        agent = self.with_accounts(self.agent(), "free", True, (answer("Hello from ChatGPT."),))
        info = agent.say("hello there")
        events = self.finish(agent)
        self.assertEqual((events[-1]["status"], events[-1]["text"]), ("done", "Hello from ChatGPT."))
        self.assertEqual(self.procs, [], "Claude is not even started")
        self.assertFalse([e for e in events if e["k"] == "notice"], "ChatGPT is the brain here, not a stand-in to announce")
        message = assistant.Chats(self.cfg).get(info["chat"])["messages"][-1]
        self.assertEqual((message["agent"], message["model"]), ("chatgpt", "default"))
        self.assertIn("[typed] hello there", self.codexes.made[0].stdin.kept)

    def test_a_claude_free_plan_alone_is_explained(self):
        assistant.configure(self.cfg, {"standin": False, "resume": False})
        agent = self.with_accounts(self.agent(), "free", False)
        agent.say("hello there")
        events = self.finish(agent)
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("free plan does not include Claude Code", events[-1]["text"])
        self.assertEqual((self.procs, self.codexes.made), ([], []))

    def test_when_claude_runs_out_chatgpt_carries_on_before_any_paid_key(self):
        agent = self.with_accounts(self.agent([[("limit", LIMIT)]]), "ok", True, (answer("Carrying on."),))
        agent.say("hello there", spoken=True)
        events = self.finish(agent)
        self.assertEqual(events[-1]["text"], "Carrying on.")
        notice = next(e for e in events if e["k"] == "notice")
        self.assertEqual((notice["text"], notice["say"]), ("ChatGPT answered this.", False), "a quiet line, not spoken, even to a spoken request")
        self.assertNotIn("limit", json.dumps([e for e in events if e["k"] == "notice"]).lower(), "limits are only mentioned when nothing can answer")
        self.assertEqual(self.asked, [], "the Groq key was not needed")

    def test_a_picked_model_that_is_resting_already_is_named_quietly(self):
        agent = self.with_accounts(self.agent([[("text", "From Sonnet.")]]), "ok", False)
        agent.cool["claude:opus"] = time.time() + 3600
        agent.say("hello there", spoken=True, model="opus")
        events = self.finish(agent)
        self.assertEqual(events[-1]["text"], "From Sonnet.")
        self.assertEqual([(e["text"], e["say"]) for e in events if e["k"] == "notice"], [("Claude Sonnet answered this.", False)])

    def test_chatgpt_can_be_picked(self):
        self.assertTrue(assistant.valid_choice("chatgpt:default"))
        assistant.configure(self.cfg, {"model": "chatgpt:default"})
        agent = self.with_accounts(self.agent([[("text", "From Claude.")]]), "ok", True, (answer("From ChatGPT."),))
        agent.say("hello there")
        self.assertEqual(self.finish(agent)[-1]["text"], "From ChatGPT.")
        self.assertEqual(self.procs, [])


class ThePickedModelAndWhatFollowsIt(BrainCase):
    """The model bar's pick answers first; then its maker's other models, nearest first; then the accounts signed in with;
    then the services connected with a key."""
    LISTED = ("gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra", "gpt-6.1-sol")

    def plan(self, choice, standin=True, chatgpt=True):
        from jcc import providers
        agent = self.agent()
        agent.brains = lambda: {"claude": "ok", "chatgpt": chatgpt}
        turn = assistant.Turn("t", "c", "auto", False, None)
        turn.choice, turn.text, turn.options = choice, "hello there", {"standin": standin}
        keys = {"groq": ["llama-a", "llama-b"], "gemini": ["gemini-pro", "gemini-flash"]}
        with mock.patch.object(codex_brain, "_listed", (time.time(), [{"id": m, "name": m} for m in self.LISTED])), \
                mock.patch.object(providers, "ready", lambda cfg, need_tools=False: ["groq", "gemini"]), \
                mock.patch.object(providers, "choices", lambda cfg, ident, most=2: keys[ident]):
            return [assistant.spec_key(spec) for spec in agent._plan(turn)]

    def test_claude_opus_then_the_smaller_claudes_then_chatgpt_then_the_keys(self):
        self.assertEqual(self.plan("opus"), ["claude:opus", "claude:sonnet", "claude:haiku", "chatgpt:default",
                                             "groq:llama-a", "gemini:gemini-pro", "groq:llama-b", "gemini:gemini-flash"])

    def test_a_chatgpt_model_then_the_nearest_ones_then_the_plan_default_then_claude(self):
        self.assertEqual(self.plan("chatgpt:gpt-6.2-sol"), ["chatgpt:gpt-6.2-sol", "chatgpt:gpt-6.2-astra", "chatgpt:gpt-6.1-terra", "chatgpt:default",
                                                            "claude:sonnet", "claude:haiku", "groq:llama-a", "gemini:gemini-pro", "groq:llama-b", "gemini:gemini-flash"])

    def test_a_gemini_model_then_geminis_own_then_claude_and_chatgpt_then_other_keys(self):
        self.assertEqual(self.plan("gemini:gemini-3-ultra"), ["gemini:gemini-3-ultra", "gemini:gemini-pro", "gemini:gemini-flash", "claude:sonnet", "claude:haiku",
                                                              "chatgpt:default", "groq:llama-a", "groq:llama-b"])

    def test_without_stand_ins_the_accounts_signed_in_with_are_still_tried(self):
        self.assertEqual(self.plan("opus", standin=False), ["claude:opus", "claude:sonnet", "claude:haiku", "chatgpt:default"])
        self.assertEqual(self.plan("gemini:gemini-3-ultra", standin=False, chatgpt=False), ["gemini:gemini-3-ultra", "gemini:gemini-pro", "gemini:gemini-flash",
                                                                                            "claude:sonnet", "claude:haiku"])

    def test_a_refused_model_rests_alone(self):
        refused = "The 'gpt-9' model is not supported when using Codex with a ChatGPT account."
        self.assertTrue(codex_brain.REFUSED_MODEL.search(refused))
        self.assertFalse(codex_brain.REFUSED_MODEL.search("You've hit your usage limit. Try again at 1:10 AM."))
        agent = self.agent()
        session = mock.Mock(spec=["spec"]); session.spec = ("api", "chatgpt", "gpt-9")
        with mock.patch.object(agent, "_end"):
            agent._cooled(assistant.Turn("t", "c", "auto", False, None), session, {"error": refused, "limit": "trouble", "until": None, "model_problem": True})
        self.assertIn("api:chatgpt:gpt-9", agent.cool)
        self.assertNotIn("api:chatgpt", agent.cool, "the plan's other ChatGPT models can still answer")
        self.assertIn("api:chatgpt:gpt-9", agent.resting())

    def test_the_menu_lists_the_models_codex_shows(self):
        listing = json.dumps({"models": [{"slug": "gpt-b", "display_name": "GPT B", "visibility": "list", "priority": 2},
                                         {"slug": "gpt-hidden", "display_name": "Hidden", "visibility": "hide", "priority": 1},
                                         {"slug": "gpt-a", "display_name": "GPT A", "visibility": "list", "priority": 1},
                                         {"slug": "bad slug; rm", "display_name": "x", "visibility": "list", "priority": 0}]})
        done = mock.Mock(stdout=listing)
        with mock.patch.object(codex_brain, "_listed", None), mock.patch("jcc.agents.resolve_command", return_value="codex.exe"), \
                mock.patch.object(codex_brain.subprocess, "run", return_value=done) as ran:
            self.assertEqual(codex_brain.models(), [{"id": "gpt-a", "name": "GPT A"}, {"id": "gpt-b", "name": "GPT B"}])
            self.assertEqual(ran.call_args[0][0], ["codex.exe", "debug", "models"])
            self.assertEqual(codex_brain.models_known(), ["gpt-a", "gpt-b"])
        with mock.patch.object(codex_brain, "_listed", None), mock.patch("jcc.agents.resolve_command", return_value=None):
            self.assertEqual(codex_brain.models(), [], "without Codex: only the plan's default is offered")


class TestAccounts(unittest.TestCase):
    def test_a_claude_free_plan_is_told_apart(self):
        free = accounts.read(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "free", "email": "someone@example.com"}), "claude", 0)
        self.assertEqual((free["signed_in"], free["plan"]), (True, "free"))
        self.assertIn("does not include Claude Code", free["note"])
        self.assertNotIn("someone@example.com", json.dumps(free), "the address it is signed in with is never kept")
        pro = accounts.read(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"}), "claude", 0)
        self.assertEqual((pro["plan"], pro.get("note")), ("pro", None))

    def test_chatgpt_sign_in(self):
        self.assertEqual(accounts.read("Logged in using ChatGPT", "codex", 0), {"signed_in": True, "how": "with your ChatGPT account"})
        self.assertFalse(accounts.read("Not logged in", "codex", 1)["signed_in"])

    def test_install_runs_the_makers_own_installer_in_a_window_the_owner_sees(self):
        for ident in ("claude", "codex"):
            for kind in ("windows", "mac"):
                script = accounts.INSTALLERS[ident][kind]
                self.assertRegex(script, r"https://(?:claude\.ai|chatgpt\.com/codex)/install\.(?:ps1|sh)")
                self.assertIn("login", script)
        with mock.patch.object(accounts.subprocess, "Popen") as started, mock.patch.object(accounts.system, "kind", lambda: "windows"), \
                mock.patch.object(accounts.os, "name", "nt"), mock.patch.object(accounts.subprocess, "CREATE_NEW_CONSOLE", 16, create=True):
            self.assertEqual(accounts.install(None, "codex")["started"], True)
        argv = started.call_args[0][0]
        self.assertEqual(argv[:4], ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"])
        self.assertIn("https://chatgpt.com/codex/install.ps1", argv[-1])
        with self.assertRaises(ValueError):
            accounts.install(None, "someone-else")

    def test_a_recent_reading_does_not_hold_a_request_up(self):
        accounts._CACHE["codex"] = (time.time(), {"signed_in": True, "how": "with your ChatGPT account"})
        try:
            with mock.patch.object(accounts, "_run", side_effect=AssertionError("read again")):
                self.assertTrue(accounts.chatgpt_ready(None))
        finally:
            accounts._CACHE.pop("codex", None)


class TestFindingCodex(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "the Windows install places")
    def test_the_official_installers_place_is_known(self):
        with tempfile.TemporaryDirectory() as home:
            exe = Path(home) / "Programs/OpenAI/Codex/bin/codex.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            agents.resolve_command.cache_clear()
            try:
                with mock.patch.dict(os.environ, {"LOCALAPPDATA": home, "APPDATA": home}), mock.patch.object(agents.shutil, "which", lambda name: None):
                    self.assertEqual(agents.resolve_command("codex"), str(exe))
            finally:
                agents.resolve_command.cache_clear()


if __name__ == "__main__":
    unittest.main()
