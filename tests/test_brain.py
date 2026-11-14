"""Which AI answers: the best model for each request, a stand-in when a usage limit is reached, carrying on by itself when
the limit is over, and compacting a long conversation. Fake Claude process, fake stand-in service, fake tools."""
import json
import threading
import time
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jcc import assistant, providers, secrets, standin, usage, voice_tools
from tests.test_assistant_voice import AssistantCase, FakeClaude, ev

LIMIT = "You've hit your 5-hour limit · resets 3:50am (Asia/Kolkata)"


def limited(text=LIMIT):
    return json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": text}) + "\n"


class ClaudeThatRunsOut(FakeClaude):
    """A Claude process whose scripts may end in a usage limit: ("limit", message)."""

    def write(self, text):
        script = self.scripts[0] if self.scripts else []
        if any(kind == "limit" for kind, _ in script):
            self.sent.append(json.loads(text))
            self.scripts.pop(0)
            for kind, value in script:
                if kind == "text":
                    self.lines.put(ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": value}}))
                elif kind == "tool":
                    name, args = value
                    self.lines.put(ev({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": name}}))
                    self.lines.put(ev({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}}))
                    self.lines.put(ev({"type": "content_block_stop", "index": 1}))
                elif kind == "limit":
                    self.lines.put(limited(value))
            return
        super().write(text)


class FakeHelper:
    def __init__(self):
        self.calls, self.closed = [], False

    def tools(self):
        return voice_tools.TOOLS

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return f"Did {name}.", False

    def close(self):
        self.closed = True


class BrainCase(AssistantCase):
    def setUp(self):
        super().setUp()
        self.asked, self.replies, self.helpers = [], [], []
        secrets.store("groq", "gsk_test_key_for_the_standin_0000")
        providers._models.clear()
        providers._models["groq"] = (time.time(), ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])

    def tearDown(self):
        secrets.delete("groq")
        providers._models.clear()
        super().tearDown()

    def agent(self, *scripts):
        def popen(argv, **kw):
            proc = ClaudeThatRunsOut(scripts[len(self.procs)] if len(self.procs) < len(scripts) else [])
            proc.argv = argv
            self.procs.append(proc)
            return proc
        agent = assistant.Assistant(self.cfg, 1234, popen, exe="claude", act=lambda kind, value=None: self.acted.append((kind, value)))
        agent.apps.refresh_soon = lambda: None
        agent.stream, agent.tool_helper = self.stream, self.helper
        self.agents.append(agent)
        return agent

    def helper(self):
        self.helpers.append(FakeHelper())
        return self.helpers[-1]

    def stream(self, cfg, ident, model, messages, tools=None, max_tokens=0, stop=None, **_):
        self.asked.append({"service": ident, "model": model, "messages": [dict(m) for m in messages], "tools": [t["function"]["name"] for t in tools or []]})
        reply = self.replies.pop(0) if self.replies else [{"text": "Okay."}]
        if isinstance(reply, Exception):
            raise reply
        yield from reply
        yield {"done": "stop", "usage": {"input": 900, "output": 12, "cached": 0}}


class TestChoosingTheModel(unittest.TestCase):
    def test_everyday_requests_get_the_quick_model_and_real_work_a_stronger_one(self):
        for text in ("open netflix", "what time is it", "play some music", "send it", "write an email to mum saying I will be late", "thanks", "pause"):
            self.assertEqual(assistant.route(text), "haiku", text)
        for text in ("write me an essay about the French revolution", "compare the iPhone and the Pixel for me", "help me decide between two laptops",
                     "analyse my spending this month", "explain why the sky is blue step by step", "draft a business plan for a bakery"):
            self.assertEqual(assistant.route(text), "sonnet", text)
        self.assertEqual(assistant.route("who won the match", research=True), "sonnet")
        self.assertEqual(assistant.route("think hard about this chess position"), "opus")
        self.assertEqual(assistant.route("use fable for this one"), "fable")

    def test_what_may_be_picked(self):
        for good in ("auto", "haiku", "sonnet", "opus", "fable", "groq:openai/gpt-oss-120b", "xai:grok-5"):
            self.assertTrue(assistant.valid_choice(good), good)
        for bad in ("gpt", "nope:model", "groq:", "", None, "groq:bad\nname"):
            self.assertFalse(assistant.valid_choice(bad), bad)

    def test_when_a_limit_ends_is_read_from_the_message(self):
        now = datetime(2026, 11, 12, 3, 4, 40).timestamp()

        def at(text):
            until = assistant.limit_until(text, now)
            return datetime.fromtimestamp(until).strftime("%d %H:%M:%S") if until else None
        self.assertEqual(at(LIMIT), "12 03:50:00")
        self.assertEqual(at("Usage limit reached. Try again in 2 hours 13 minutes."), "12 05:17:40")
        self.assertEqual(at("limit reached ∙ resets 9pm"), "12 21:00:00")
        self.assertEqual(at("resets Nov 14, 9pm"), "14 21:00:00")
        self.assertEqual(at("Try again at 2:15 AM."), "13 02:15:00", "a time that has passed today is tomorrow")
        self.assertEqual(at("rate limited, retry in 45 seconds"), "12 03:05:25")
        self.assertIsNone(at("something else went wrong"))
        self.assertTrue(assistant.is_limit(LIMIT))


class TestStandIn(BrainCase):
    def test_when_claude_runs_out_another_ai_carries_on_and_the_owner_is_told(self):
        agent = self.agent([[("limit", LIMIT)]])
        self.replies = [[{"text": "It is four "}, {"text": "o'clock."}]]
        info = agent.say("what time is it in Tokyo", spoken=True)
        events = self.finish(agent)
        self.assertEqual((events[-1]["status"], events[-1]["text"]), ("done", "It is four o'clock."))
        notice = next(e for e in events if e["k"] == "notice")
        self.assertEqual(notice["kind"], "switch")
        self.assertRegex(notice["text"], r"Claude Haiku has reached its limit until .*\. I am carrying on with Groq\.")
        self.assertTrue(notice["say"], "said out loud, because the request was spoken")
        self.assertEqual((self.asked[0]["service"], self.asked[0]["model"]), ("groq", "openai/gpt-oss-120b"))
        self.assertIn("[spoken] what time is it in Tokyo", self.asked[0]["messages"][-1]["content"])
        self.assertNotIn("see_screen", self.asked[0]["tools"], "a stand-in is not given tools that need it to look at pictures")
        self.assertIn("open_app", self.asked[0]["tools"])
        message = assistant.Chats(self.cfg).get(info["chat"])["messages"][-1]
        self.assertEqual((message["status"], message["agent"], message["model"], message["switched"]), ("done", "groq", "openai/gpt-oss-120b", ["Claude Haiku"]))
        self.assertGreater(agent.cool["claude"], time.time(), "Claude is left alone until its allowance is back")
        self.assertEqual(usage.Usage(self.cfg.state_dir, self.cfg.caps).cooldowns().get("claude"), agent.cool["claude"], "and the coding jobs know it too")
        # The next request does not even try Claude.
        before = agent.poll(0)["next"]
        agent.say("and in Paris?", info["chat"], spoken=True)
        later = self.finish(agent, before)
        self.assertEqual(later[-1]["status"], "done")
        self.assertEqual(len(self.procs), 1, "no new Claude process was started")
        self.assertFalse([e for e in later if e["k"] == "notice"], "and the owner is not told again")
        self.assertEqual(len(self.asked[1]["messages"]), 4, "the same stand-in conversation carries on: instructions, question, answer, question")
        self.assertTrue(agent.poll(0)["brain"]["until"] > time.time())
        # When the allowance is back, Claude answers again.
        agent.cool.clear()
        self.assertEqual(agent.poll(0)["brain"], {})

    def test_a_task_that_was_under_way_is_taken_over_from_where_it_stopped(self):
        agent = self.agent([[("text", "Sure. "), ("tool", ("mcp__jarvis__open_app", {"name": "Notepad"})), ("limit", LIMIT)]])
        self.replies = [[{"call": {"id": "c1", "name": "type_into", "arguments": {"text": "Dear Sam"}}}], [{"text": "It is written."}]]
        info = agent.say("open notepad and type Dear Sam", spoken=False)
        events = self.finish(agent)
        self.assertEqual(events[-1]["status"], "done")
        self.assertEqual([e["t"] for e in events if e["k"] == "step"], ["Opening Notepad", "Filling in a box"])
        handed = self.asked[0]["messages"][-1]["content"]
        self.assertIn("It had already done this, which must not be done again: Opening Notepad.", handed)
        self.assertIn('It had said so far: "Sure."', handed)
        self.assertEqual(self.helpers[0].calls, [("type_into", {"text": "Dear Sam"})], "the stand-in used the same tools")
        self.assertEqual(self.asked[1]["messages"][-1], {"role": "tool", "tool_call_id": "c1", "content": "Did type_into."})
        content = assistant.Chats(self.cfg).get(info["chat"])["messages"][-1]["content"]
        self.assertEqual(content, "Sure.\n\nIt is written.", "one answer, whoever wrote which part")
        rows = usage.turns(self.cfg.state_dir)
        self.assertEqual({(row["engine"], row["model"]) for row in rows}, {("groq", "openai/gpt-oss-120b"), ("claude", "haiku")})

    def test_with_no_one_left_the_request_waits_and_is_carried_on_with_by_itself(self):
        agent = self.agent([[("limit", LIMIT)]], [[("text", "Here is your plan.")]])
        self.replies = [providers.ProviderError("Groq has reached its limit.", limit=True, retry_at=time.time() + 900)]
        info = agent.say("plan my week", spoken=True)
        events = self.finish(agent)
        self.assertEqual(events[-1]["status"], "paused")
        self.assertRegex(events[-1]["text"], r"Every AI I can use has reached its limit, so this is paused\. I will carry on with it by myself at ")
        self.assertEqual([e["kind"] for e in events if e["k"] == "notice"], ["waiting"])
        waiting = agent.poll(0)["brain"]["waiting"]
        self.assertEqual((len(waiting), waiting[0]["chat"], waiting[0]["text"]), (1, info["chat"], "plan my week"))
        saved = json.loads((self.cfg.state_dir / "assistant-waiting.json").read_text("utf-8"))
        self.assertEqual(saved[0]["id"], info["id"], "kept on disk, so a restart does not lose it")
        self.assertEqual(agent.resume_check(), 0, "not before the allowance is back")
        agent.cool.clear()
        again = assistant.Assistant(self.cfg, 1234, lambda argv, **kw: self.procs.append(ClaudeThatRunsOut([[("text", "Here is your plan.")]])) or self.procs[-1], exe="claude")
        again.apps.refresh_soon = lambda: None
        self.agents.append(again)
        self.assertEqual([w["id"] for w in again.waiting], [info["id"]], "a new run of the app finds it again")
        again.cool.clear()
        before = again.poll(0)["next"]
        self.assertEqual(again.resume_check(now=True), 1)
        events = self.finish(again, before)
        self.assertEqual((events[-1]["status"], events[-1]["text"]), ("done", "Here is your plan."))
        self.assertIn("carrying on with", next(e["text"] for e in events if e["k"] == "notice"))
        messages = assistant.Chats(self.cfg).get(info["chat"])["messages"]
        self.assertEqual([(m["role"], m.get("status")) for m in messages], [("user", None), ("assistant", "done")], "answered in place: the question is not asked twice")
        self.assertEqual(again.waiting, [])
        sent = self.procs[-1].sent[0]["message"]["content"][0]["text"]
        self.assertIn("plan my week", sent)

    def test_a_waiting_request_can_be_called_off(self):
        agent = self.agent([[("limit", LIMIT)]])
        self.replies = [providers.ProviderError("Groq has reached its limit.", limit=True, retry_at=time.time() + 900)]
        info = agent.say("plan my week")
        self.finish(agent)
        self.assertEqual(agent.unwait(info["id"]), {"ok": True})
        self.assertEqual((agent.waiting, agent.unwait(info["id"])), ([], {"ok": False}))
        self.assertEqual(assistant.Chats(self.cfg).get(info["chat"])["messages"][-1]["status"], "cancelled")

    def test_the_owner_can_switch_stand_ins_off(self):
        assistant.configure(self.cfg, {"standin": False, "resume": False})
        agent = self.agent([[("limit", LIMIT)]])
        agent.say("hello there")
        events = self.finish(agent)
        self.assertEqual(events[-1]["status"], "failed")
        self.assertRegex(events[-1]["text"], r"Every AI I can use has reached its limit\. They are available again at ")
        self.assertEqual((self.asked, agent.waiting), ([], []))

    def test_trouble_that_is_not_a_limit_also_brings_in_a_stand_in(self):
        agent = self.agent([[("limit", "Invalid API key · Please run /login")]])
        self.replies = [[{"text": "Hello."}]]
        agent.say("hello there")
        events = self.finish(agent)
        self.assertEqual(events[-1]["status"], "done")
        self.assertIn("could not answer just now", next(e["text"] for e in events if e["k"] == "notice"))

    def test_a_picked_stand_in_answers_first_and_claude_is_its_stand_in(self):
        assistant.configure(self.cfg, {"model": "groq:openai/gpt-oss-20b"})
        agent = self.agent([[("text", "From Claude.")]])
        self.replies = [[{"text": "From Groq."}], providers.ProviderError("Groq has reached its limit.", limit=True, retry_at=time.time() + 600)]
        first = agent.say("hello there")
        self.assertEqual(self.finish(agent)[-1]["text"], "From Groq.")
        self.assertEqual(self.asked[0]["model"], "openai/gpt-oss-20b")
        before = agent.poll(0)["next"]
        agent.say("and again", first["chat"])
        events = self.finish(agent, before)
        self.assertEqual(events[-1]["text"], "From Claude.")
        self.assertIn("assistant: From Groq.", self.procs[0].sent[0]["message"]["content"][0]["text"], "Claude is told what was said before it came in")

    def test_each_brain_keeps_its_own_session_for_a_chat(self):
        agent = self.agent([[("text", "Quick answer.")], [("text", "Thanks noted.")]], [[("text", "A long essay.")]])
        first = agent.say("hello there")
        self.finish(agent)
        before = agent.poll(0)["next"]
        agent.say("write me an essay about rivers", first["chat"])
        self.finish(agent, before)
        self.assertEqual([proc.argv[proc.argv.index("--model") + 1] for proc in self.procs], ["haiku", "sonnet"])
        self.assertEqual(len(agent.alt), 1, "the quick model's session stays warm beside it")
        essay = self.procs[1].sent[0]["message"]["content"][0]["text"]
        self.assertIn("Earlier in this conversation", essay)
        before = agent.poll(0)["next"]
        agent.say("thanks", first["chat"])
        self.finish(agent, before)
        self.assertEqual(len(self.procs), 2, "going back to the quick model costs no new start")
        back = self.procs[0].sent[1]["message"]["content"][0]["text"]
        self.assertIn("Since your last reply here, another AI model answered the user:", back)
        self.assertIn('The user asked: "write me an essay about rivers"', back)

    def test_the_numbers_of_every_answer_are_kept(self):
        agent = self.agent([[("text", "Hi.")]])
        agent.say("hello there", spoken=True)
        self.finish(agent)
        self.assertEqual(usage.turns(self.cfg.state_dir), [], "a reply with no numbers is not counted")
        usage.log_turn(self.cfg.state_dir, {"engine": "claude", "model": "haiku", "spoken": True, "status": "done", "input": 4, "cached": 9368, "written": 489,
                                           "output": 12, "cost": 0.0003, "seconds": 1.1, "first": 0.8, "tools": 1})
        rows = usage.turns(self.cfg.state_dir)
        self.assertEqual((rows[0]["engine"], rows[0]["requests"], rows[0]["cached"], rows[0]["done"]), ("claude", 1, 9368, 1))


class TestCompacting(BrainCase):
    def test_a_long_conversation_is_shortened_to_a_summary_and_carries_on_from_it(self):
        agent = self.agent([[("text", "Paris.")], [("text", "About two million.")],
                            [("text", "The user asked about Paris: capital of France, about two million people. They prefer short answers.")]],
                           [[("text", "The Seine.")]])
        first = agent.say("what is the capital of France")
        self.finish(agent)
        with self.assertRaises(ValueError):
            agent.compact(first["chat"])                   # too short to be worth it
        before = agent.poll(0)["next"]
        agent.say("how many people live there", first["chat"])
        self.finish(agent, before)
        before = agent.poll(0)["next"]
        info = agent.say("/compact", first["chat"])
        events = self.finish(agent, before)
        self.assertEqual((info["model"], events[-1]["status"], events[-1]["compact"]), ("compact", "done", True))
        self.assertIn("Conversation compacted.", events[-1]["text"])
        chat = assistant.Chats(self.cfg).get(first["chat"])
        self.assertEqual(len(chat["messages"]), 5, "nothing was removed, and '/compact' itself is not a message")
        self.assertIn("capital of France", chat["summary"])
        self.assertIn("Write a summary of this whole conversation", self.procs[0].sent[2]["message"]["content"][0]["text"])
        self.assertEqual(agent.sessions, {}, "the old session, with every word in it, is let go")
        before = agent.poll(0)["next"]
        agent.say("which river runs through it", first["chat"])
        self.finish(agent, before)
        sent = self.procs[1].sent[0]["message"]["content"][0]["text"]
        self.assertIn("Summary of the conversation so far:\nThe user asked about Paris", sent)
        self.assertNotIn("About two million.", sent, "the summary stands in for the old messages")


class TestStandInSession(unittest.TestCase):
    def test_tools_are_used_and_reported_like_claudes(self):
        asked = []
        replies = [[{"text": "One moment. "}, {"call": {"id": "a", "name": "open_app", "arguments": {"name": "Spotify"}}}], [{"text": "Spotify is open."}]]

        def stream(cfg, ident, model, messages, tools=None, **_):
            asked.append([dict(m) for m in messages])
            yield from replies.pop(0)
            yield {"done": "stop", "usage": {"input": 500, "output": 10, "cached": 100}}
        helper = FakeHelper()
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=lambda: helper, stream=stream)
        events = list(session.events("[spoken] open spotify"))
        kinds = [(e["event"]["type"] if e["type"] == "stream_event" else e["type"]) for e in events]
        self.assertEqual(kinds, ["content_block_start", "content_block_delta", "content_block_stop", "content_block_delta", "result"],
                         "a few words before a tool are the model getting ahead of itself: they are not passed on (or they would be said twice)")
        self.assertEqual(events[0]["event"]["content_block"]["name"], "mcp__jarvis__open_app")
        self.assertEqual((events[-1]["is_error"], events[-1]["result"], events[-1]["usage"]), (False, "Spotify is open.", {"input": 1000, "output": 20, "cached": 200}))
        self.assertEqual(asked[1][-2]["tool_calls"][0]["function"], {"name": "open_app", "arguments": '{"name": "Spotify"}'})
        self.assertNotIn("content", asked[1][-2])
        self.assertEqual(helper.calls, [("open_app", {"name": "Spotify"})])
        session.close()
        self.assertTrue(helper.closed and not session.alive())

    def test_a_short_answer_written_twice_is_said_once(self):
        for raw, meant in (("Paused.Paused.", "Paused."), ("Paused.[not for me]", "Paused."), ("Opened Gmail.Done.", "Opened Gmail. Done."), ("Done. Done.", "Done."),
                           ("[not for me]", "[not for me]"), ("It is 4 pm. The U.S.A. is far away.", "It is 4 pm. The U.S.A. is far away."), ("Visit example.com today.", "Visit example.com today.")):
            self.assertEqual(standin.tidy(raw), meant, raw)

        def stream(cfg, ident, model, messages, tools=None, **_):
            yield {"text": "Paused"}
            yield {"text": ".Paused."}
            yield {"done": "stop", "usage": {}}
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=FakeHelper, stream=stream)
        events = list(session.events("pause it"))
        self.assertEqual((events[0]["event"]["delta"]["text"], events[-1]["result"], session.messages[-1]["content"]), ("Paused.", "Paused.", "Paused."))

    def test_a_real_answer_flows_as_it_is_written(self):
        long = "The French Revolution began in 1789 and changed the country from a kingdom into a republic over the next ten years. "

        def stream(cfg, ident, model, messages, tools=None, **_):
            yield {"text": long[:60]}
            yield {"text": long[60:]}
            yield {"text": "It ended with Napoleon."}
            yield {"done": "stop", "usage": {}}
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=FakeHelper, stream=stream)
        pieces = [e["event"]["delta"]["text"] for e in session.events("tell me about it") if e["type"] == "stream_event"]
        self.assertEqual(pieces, [long, "It ended with Napoleon."], "held only until it is clear that it is an answer")

    def test_a_service_that_asks_for_a_few_seconds_is_given_them_once(self):
        asked = []

        def stream(cfg, ident, model, messages, tools=None, **_):
            asked.append(time.time())
            if len(asked) == 1:
                raise providers.ProviderError("Groq has reached its limit: try again in 0.2s", limit=True, retry_at=time.time() + 0.2)
            yield {"text": "Here you are."}
            yield {"done": "stop", "usage": {}}
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=FakeHelper, stream=stream)
        result = list(session.events("hello"))[-1]
        self.assertEqual((result["is_error"], result["result"], len(asked)), (False, "Here you are.", 2))
        self.assertGreater(asked[1] - asked[0], 0.2)

        def always(cfg, ident, model, messages, tools=None, **_):
            raise providers.ProviderError("Groq has reached its limit.", limit=True, retry_at=time.time() + 900)
            yield  # pragma: no cover
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=FakeHelper, stream=always)
        self.assertTrue(list(session.events("hello"))[-1]["limit"], "a long wait is not waited out: another AI is asked instead")

    def test_a_service_that_refuses_says_so_and_nothing_is_left_half_asked(self):
        def stream(cfg, ident, model, messages, tools=None, **_):
            raise providers.ProviderError("Groq has reached its limit.", limit=True, retry_at=123.0)
            yield  # pragma: no cover
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=FakeHelper, stream=stream)
        result = list(session.events("hello"))[-1]
        self.assertEqual((result["is_error"], result["limit"], result["retry_at"]), (True, True, 123.0))
        self.assertEqual(len(session.messages), 1, "the question that never got an answer is not kept")

    def test_a_long_talk_is_sent_in_part_and_old_tool_reports_are_cut_short(self):
        session = standin.ApiSession(None, "groq", "m", "You are JARVIS.", "s1", helper=FakeHelper, stream=lambda *a, **k: iter(()))
        for n in range(20):
            session.messages += [{"role": "user", "content": f"question {n}"}, {"role": "assistant", "tool_calls": [{"id": str(n)}]},
                                 {"role": "tool", "tool_call_id": str(n), "content": "x" * 3000}, {"role": "assistant", "content": f"answer {n}"}]
        window = session._window()
        self.assertEqual(window[0]["role"], "system")
        self.assertEqual(window[1]["role"], "user", "the part that is sent starts with a question, never in the middle of a tool's use")
        self.assertLess(len(window), 20)
        self.assertTrue(all(len(m["content"]) <= 402 for m in window[:-4] if m["role"] == "tool"))
        self.assertEqual(len(session.messages), 81, "the session itself forgets nothing")

    def test_the_lean_tool_list(self):
        lean, full = standin.shape(voice_tools.TOOLS, True), standin.shape(voice_tools.TOOLS, False)
        names = [tool["function"]["name"] for tool in lean]
        self.assertTrue({"open_app", "play_music", "send_email", "click_control"} <= set(names))
        self.assertFalse({"see_screen", "click", "approve"} & set(names))
        self.assertLess(len(json.dumps(lean)), 0.62 * len(json.dumps(full)), "one sentence each: several services allow only a few thousand tokens a minute")
        self.assertTrue(all(tool["function"]["description"].endswith((".", "!", "?")) for tool in lean))


class FakeService(BaseHTTPRequestHandler):
    """A stand-in for an AI service that speaks the OpenAI chat format."""
    answers: list = []
    seen: list = []

    def log_message(self, *args):
        pass

    def _send(self, status, body, kind="application/json", headers=()):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good-key-123456":
            return self._send(401, {"error": {"message": "Incorrect API key provided: sk-secretsecretsecretsecret"}})
        self._send(200, {"data": [{"id": "big-model"}, {"id": "text-embedding-3"}, {"id": "small-model-fast"}, {"id": "whisper-large"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        FakeService.seen.append(body)
        answer = FakeService.answers.pop(0) if FakeService.answers else (200, [{"choices": [{"delta": {"content": "Hi"}}]}])
        status, rows = answer[0], answer[1]
        if status != 200:
            return self._send(status, rows, headers=answer[2] if len(answer) > 2 else ())
        raw = "".join("data: " + json.dumps(row) + "\n\n" for row in rows) + "data: [DONE]\n\n"
        self._send(200, raw.encode(), "text/event-stream")


class TestServices(AssistantCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeService)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        FakeService.answers, FakeService.seen = [], []
        providers._models.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        secrets.delete("ai-custom")
        providers._models.clear()
        super().tearDown()

    def test_connecting_checks_the_key_and_reads_the_real_model_list(self):
        with self.assertRaises(providers.ProviderError) as refused:
            providers.connect(self.cfg, "custom", "wrong-key-123456", self.address, "My server")
        self.assertIn("did not accept the key", str(refused.exception))
        self.assertNotIn("sk-secret", str(refused.exception))
        self.assertIsNone(secrets.get("ai-custom"), "a key the service refuses is not kept")
        self.assertFalse(providers.connected(self.cfg, "custom"))
        entry = providers.connect(self.cfg, "custom", "good-key-123456", self.address, "My server")
        self.assertEqual((entry["connected"], entry["name"], entry["model"], entry["address"]), (True, "My server", "big-model", self.address))
        self.assertEqual(providers.models(self.cfg, "custom"), ["big-model", "small-model-fast"], "only models one can chat with")
        self.assertNotIn("good-key", json.dumps(providers.listing(self.cfg)), "a key is never part of what the window is sent")
        self.assertEqual(providers.choose_model(self.cfg, "custom", "small-model-fast")["model"], "small-model-fast")
        self.assertIn("custom", providers.ready(self.cfg))
        self.assertFalse(providers.disconnect(self.cfg, "custom")["connected"])
        self.assertIsNone(secrets.get("ai-custom"))

    def test_only_a_safe_address_is_accepted(self):
        for bad in ("http://example.com/v1", "ftp://example.com", "https://user:pw@example.com/v1", "example.com", ""):
            with self.assertRaises(providers.ProviderError):
                providers.check_address(bad)
        self.assertEqual(providers.check_address("https://api.example.com/v1/"), "https://api.example.com/v1")
        self.assertEqual(providers.check_address("http://localhost:1234/v1"), "http://localhost:1234/v1")

    def test_an_answer_arrives_piece_by_piece_with_tool_calls_and_token_counts(self):
        providers.connect(self.cfg, "custom", "good-key-123456", self.address)
        FakeService.answers = [(200, [{"choices": [{"delta": {"content": "Let me "}}]}, {"choices": [{"delta": {"content": "see."}}]},
                                      {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c9", "function": {"name": "open_app", "arguments": '{"na'}}]}}]},
                                      {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'me": "Notepad"}'}}]}, "finish_reason": "tool_calls"}]},
                                      {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 9, "prompt_tokens_details": {"cached_tokens": 100}}}])]
        pieces = list(providers.stream(self.cfg, "custom", "big-model", [{"role": "user", "content": "open notepad, key gsk_abcdefghijklmnopqrstu"}], tools=[{"type": "function"}]))
        self.assertEqual(pieces, [{"text": "Let me "}, {"text": "see."}, {"call": {"id": "c9", "name": "open_app", "arguments": {"name": "Notepad"}}},
                                  {"done": "tool_calls", "usage": {"input": 120, "output": 9, "cached": 100}}])
        sent = FakeService.seen[-1]
        self.assertEqual((sent["model"], sent["stream"]), ("big-model", True))
        self.assertNotIn("gsk_abc", json.dumps(sent), "secrets are taken out of what is sent")

    def test_a_used_up_allowance_is_told_apart_from_other_trouble(self):
        providers.connect(self.cfg, "custom", "good-key-123456", self.address)
        FakeService.answers = [(429, {"error": {"message": "Rate limit reached for requests"}}, [("Retry-After", "42")]),
                               (404, {"error": {"message": "The model `gone` does not exist"}}), (500, {"error": {"message": "boom"}})]
        with self.assertRaises(providers.ProviderError) as slow:
            list(providers.stream(self.cfg, "custom", "big-model", [{"role": "user", "content": "hi"}]))
        self.assertTrue(slow.exception.limit)
        self.assertAlmostEqual(slow.exception.retry_at, time.time() + 42, delta=3)
        with self.assertRaises(providers.ProviderError) as missing:
            list(providers.stream(self.cfg, "custom", "gone", [{"role": "user", "content": "hi"}]))
        self.assertTrue(missing.exception.model_problem and not missing.exception.limit)
        with self.assertRaises(providers.ProviderError) as broken:
            list(providers.stream(self.cfg, "custom", "big-model", [{"role": "user", "content": "hi"}]))
        self.assertTrue(broken.exception.limit, "a service in trouble is left alone for a moment, like one that is out")

    def test_every_known_service_has_what_the_list_needs(self):
        for ident, entry in providers.CATALOG.items():
            self.assertTrue(entry["name"] and entry["about"] and entry.get("prefer"), ident)
            self.assertTrue(ident == "custom" or entry["base"].startswith("https://") or entry.get("local"), ident)
            self.assertIn(providers.key_name(ident), secrets.ENV_NAMES, ident) if not entry.get("local") else None
        self.assertEqual(len(providers.listing(self.cfg)), len(providers.CATALOG))


if __name__ == "__main__":
    unittest.main()
