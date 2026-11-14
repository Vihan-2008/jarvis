"""Research: who does it (Perplexity at a chosen depth, or Claude with its web search), what is sent, and what it costs."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jcc import assistant, memory, providers, secrets, usage
from jcc.chats import Chats
from tests.test_assistant_voice import AssistantCase
from tests.test_brain import BrainCase

KEY = "pplx-good-key-123456"
DONE = {"type": "response.completed", "response": {
    "id": "resp_1", "model": "openai/gpt-5.6-sol", "status": "completed",
    "output": [{"type": "search_results", "results": [
                   {"id": 1, "title": "France - Wikipedia", "url": "https://en.wikipedia.org/wiki/France", "snippet": "France is a country..."},
                   {"id": 2, "title": "Bad [link]", "url": "javascript:alert(1)"},
                   {"id": 3, "title": "", "url": "https://www.britannica.com/place/Paris"},
                   {"id": 4, "title": "France again", "url": "https://en.wikipedia.org/wiki/France"}]},
               {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Paris is the capital."}]}],
    "usage": {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500, "cost": {"input_cost": 0.01, "output_cost": 0.0023, "total_cost": 0.0123, "currency": "USD"}}}}


class FakePerplexity(BaseHTTPRequestHandler):
    """A stand-in for Perplexity's Agent API (POST /v1/agent, answers in the "responses" shape)."""
    answers: list = []
    seen: list = []

    def log_message(self, *args):
        pass

    def _send(self, status, body, kind="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(404, {"error": {"message": "Not found"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        FakePerplexity.seen.append((self.path, body))
        if self.headers.get("Authorization") != "Bearer " + KEY:
            return self._send(401, {"error": {"message": "Invalid API key"}})
        if "input" not in body:
            return self._send(400, {"error": {"message": "input is required"}})
        answer = FakePerplexity.answers.pop(0) if FakePerplexity.answers else [{"type": "response.output_text.delta", "delta": "Paris is"},
                                                                               {"type": "response.output_text.delta", "delta": " the capital."}, DONE]
        if isinstance(answer, dict):                                    # answered all at once, not piece by piece
            return self._send(200, answer)
        raw = "".join(f"event: {row['type']}\ndata: {json.dumps(row)}\n\n" for row in answer)
        self._send(200, raw.encode(), "text/event-stream")


class TestPerplexity(AssistantCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePerplexity)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.real = providers.CATALOG["perplexity"]["base"]
        providers.CATALOG["perplexity"]["base"] = f"http://127.0.0.1:{self.server.server_address[1]}"
        FakePerplexity.answers, FakePerplexity.seen = [], []
        providers._models.clear()
        providers._failed.clear()

    def tearDown(self):
        providers.CATALOG["perplexity"]["base"] = self.real
        self.server.shutdown()
        self.server.server_close()
        secrets.delete("ai-perplexity")
        providers._models.clear()
        providers._failed.clear()
        super().tearDown()

    def test_its_address_and_its_depths_of_research(self):
        self.assertEqual(self.real, "https://api.perplexity.ai")
        self.assertEqual(providers.CATALOG["perplexity"]["models"], ["fast", "low", "medium", "high", "xhigh", "ultra"])
        self.assertEqual(sorted(providers.EFFORTS), sorted(providers.CATALOG["perplexity"]["models"]))
        self.assertFalse(providers.CATALOG["perplexity"].get("tools", True), "it searches and answers; it is never given control of the PC")

    def test_the_key_is_checked_without_asking_anything(self):
        with self.assertRaises(providers.ProviderError) as refused:
            providers.connect(self.cfg, "perplexity", "pplx-wrong-key-123456")
        self.assertIn("did not accept the key", str(refused.exception))
        self.assertIsNone(secrets.get("ai-perplexity"), "a key the service refuses is not kept")
        entry = providers.connect(self.cfg, "perplexity", KEY)
        self.assertEqual((entry["connected"], entry["model"], entry["search"]), (True, "low", True))
        self.assertEqual([(path, body) for path, body in FakePerplexity.seen], [("/v1/agent", {}), ("/v1/agent", {})],
                         "an empty request: turned away as no request at all when the key is good, so nothing is ever charged for checking")
        self.assertEqual(providers.models(self.cfg, "perplexity"), ["fast", "low", "medium", "high", "xhigh", "ultra"])
        self.assertEqual(len(FakePerplexity.seen), 2, "its choices are fixed: it is not asked for them again")

    def test_an_answer_arrives_piece_by_piece_with_its_sources_and_what_it_cost(self):
        secrets.store("ai-perplexity", KEY)
        pieces = list(providers.stream(self.cfg, "perplexity", "medium", [{"role": "system", "content": "You are JARVIS. The user's sister is called Mira."},
                                                                          {"role": "user", "content": "What is the capital of France?"}]))
        self.assertEqual("".join(p["text"] for p in pieces if "text" in p), "Paris is the capital.")
        self.assertEqual(next(p["sources"] for p in pieces if "sources" in p),
                         [{"title": "France - Wikipedia", "url": "https://en.wikipedia.org/wiki/France"}, {"title": "www.britannica.com", "url": "https://www.britannica.com/place/Paris"}],
                         "web pages only, each once; one without a title is named after its site")
        self.assertEqual(pieces[-1], {"done": "stop", "usage": {"input": 1200, "output": 300, "cached": 0, "cost": 0.0123}})
        path, body = FakePerplexity.seen[-1]
        self.assertEqual((path, body), ("/v1/agent", {"input": "What is the capital of France?", "stream": True, "effort": "medium"}),
                         "a depth of research brings its own instructions: ours (and what is in them) are not sent")

    def test_a_named_model_and_a_whole_conversation(self):
        secrets.store("ai-perplexity", KEY)
        talk = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Capital of France?"}, {"role": "assistant", "content": "Paris."},
                {"role": "user", "content": "And of Japan?"}]
        list(providers.stream(self.cfg, "perplexity", "perplexity/sonar", talk, max_tokens=700))
        body = FakePerplexity.seen[-1][1]
        self.assertEqual(body, {"input": talk[1:], "stream": True, "model": "perplexity/sonar", "tools": [{"type": "web_search"}], "max_output_tokens": 700, "instructions": "Be brief."})

    def test_an_answer_that_comes_all_at_once(self):
        secrets.store("ai-perplexity", KEY)
        FakePerplexity.answers = [DONE["response"]]
        got = providers.ask(self.cfg, "perplexity", "fast", "", "Capital of France?")
        self.assertEqual((got["text"], got["usage"]["cost"], len(got["sources"])), ("Paris is the capital.", 0.0123, 2))

    def test_its_troubles_are_told_apart(self):
        secrets.store("ai-perplexity", KEY)
        FakePerplexity.answers = [[{"type": "response.output_text.delta", "delta": "Par"}, {"type": "response.failed", "response": {"error": {"message": "You exceeded your current quota"}}}]]
        with self.assertRaises(providers.ProviderError) as out:
            list(providers.stream(self.cfg, "perplexity", "low", [{"role": "user", "content": "x"}]))
        self.assertTrue(out.exception.limit, "an allowance that is used up: another AI carries on")
        secrets.store("ai-perplexity", "pplx-wrong-key-123456")
        with self.assertRaises(providers.ProviderError) as refused:
            list(providers.stream(self.cfg, "perplexity", "low", [{"role": "user", "content": "x"}]))
        self.assertEqual((refused.exception.status, refused.exception.limit), (401, False))


class ResearchCase(BrainCase):
    def setUp(self):
        super().setUp()
        self.cost = 0.0

    def tearDown(self):
        secrets.delete("ai-perplexity")
        super().tearDown()

    def connect(self):
        secrets.store("ai-perplexity", KEY)

    def stream(self, cfg, ident, model, messages, tools=None, max_tokens=0, stop=None, **_):
        self.asked.append({"service": ident, "model": model, "messages": [dict(m) for m in messages], "tools": [t["function"]["name"] for t in tools or []]})
        reply = self.replies.pop(0) if self.replies else [{"text": "Okay."}]
        if isinstance(reply, Exception):
            raise reply
        yield from reply
        yield {"done": "stop", "usage": {"input": 900, "output": 120, "cached": 0, "cost": self.cost}}


class TestWhoDoesResearch(ResearchCase):
    def test_what_may_be_chosen(self):
        for good in ("auto", "perplexity:fast", "perplexity:medium", "perplexity:ultra", "claude:sonnet", "claude:opus", "claude:fable"):
            self.assertTrue(assistant.valid_research(good), good)
        for bad in ("", None, "perplexity", "perplexity:sonar", "claude:haiku", "claude:gpt", "groq:openai/gpt-oss-120b", 5, "auto ", "perplexity:medium;rm"):
            self.assertFalse(assistant.valid_research(bad), repr(bad))
        self.assertEqual(assistant.settings(self.cfg)["research"], "auto")
        self.assertEqual(assistant.configure(self.cfg, {"research": "perplexity:high"})["research"], "perplexity:high")
        with self.assertRaises(ValueError):
            assistant.configure(self.cfg, {"research": "claude:haiku"})

    def test_left_to_jarvis_it_is_the_service_made_for_it_or_claude_with_its_web_search(self):
        agent = self.agent()
        self.assertEqual(agent._first("auto", "how do heat pumps work", research=True), ("claude", "sonnet"), "Perplexity is not connected")
        self.assertEqual(agent._first("opus", "how do heat pumps work", research=True), ("claude", "opus"), "a stronger Claude model picked for the message is kept")
        self.assertEqual(agent._first("haiku", "how do heat pumps work", research=True), ("claude", "sonnet"), "the quick model is not one for research")
        self.connect()
        self.assertEqual(agent._first("auto", "how do heat pumps work", research=True), ("api", "perplexity", "medium"))
        self.assertEqual(agent._first("auto", "how do heat pumps work"), ("claude", "haiku"), "an everyday question is not sent there")

    def test_the_owner_can_choose_and_change_it_for_one_request(self):
        agent = self.agent()
        self.connect()
        assistant.configure(self.cfg, {"research": "perplexity:high"})
        self.assertEqual(agent._first("auto", "x", research=True), ("api", "perplexity", "high"))
        self.assertEqual(agent._first("auto", "x", research=True, how="claude:opus"), ("claude", "opus"), "for this one request")
        self.assertEqual(agent._first("auto", "x", research=True, how="perplexity:fast"), ("api", "perplexity", "fast"))
        self.assertEqual(agent._first("auto", "x", research=True, how="nonsense"), ("api", "perplexity", "high"), "anything else: the usual choice")
        assistant.configure(self.cfg, {"research": "claude:fable"})
        self.assertEqual(agent._first("auto", "x", research=True), ("claude", "fable"))
        secrets.delete("ai-perplexity")
        assistant.configure(self.cfg, {"research": "perplexity:high"})
        self.assertEqual(agent._first("auto", "x", research=True), ("claude", "sonnet"), "the chosen service is no longer connected: Claude does it")

    def test_who_carries_on_if_the_first_cannot(self):
        agent = self.agent()
        self.connect()
        turn = assistant.Turn("r1", "c1", "", False, None)
        turn.text, turn.research, turn.choice, turn.options = "compare heat pumps", True, "auto", assistant.settings(self.cfg)
        plan = agent._plan(turn)
        self.assertEqual(plan[:2], [("api", "perplexity", "medium"), ("claude", "sonnet")], "then Claude with its web search, not the quick model")
        turn.how = "claude:opus"
        plan = agent._plan(turn)
        self.assertEqual(plan[0], ("claude", "opus"))
        self.assertLess(plan.index(("api", "perplexity", "medium")), plan.index(("api", "groq", "openai/gpt-oss-120b")), "a service that searches comes before one that cannot")


class TestAResearchRequest(ResearchCase):
    def test_perplexity_is_sent_the_question_and_nothing_about_the_pc_or_its_owner(self):
        self.connect()
        memory.remember(self.cfg, "The owner's sister is called Mira.")
        self.assertIn("Mira", assistant.standin_prompt(self.cfg, assistant.settings(self.cfg), assistant.active_assistant(self.cfg)), "(a brain that acts on the PC is told)")
        agent = self.agent()
        agent.look = lambda: "In front: Bank statement - Excel. Also open: Inbox (3) - Outlook."
        self.cost = 0.0412
        self.replies = [[{"text": "## Heat pumps\nThey move heat rather than make it."}, {"sources": [{"title": "Heat pump - Wikipedia", "url": "https://en.wikipedia.org/wiki/Heat_pump"}]}]]
        started = agent.say("How do heat pumps work?", research=True)
        self.finish(agent)
        asked = self.asked[0]
        self.assertEqual((asked["service"], asked["model"], asked["tools"]), ("perplexity", "medium", []))
        system, question = asked["messages"][0]["content"], asked["messages"][-1]["content"]
        self.assertEqual(system, assistant.PLAIN.format(name="JARVIS"))
        self.assertNotIn("Mira", system + question, "nothing it remembers about its owner")
        self.assertNotIn("Excel", question, "nothing that is on the screen")
        self.assertNotIn("[typed]", question)
        self.assertTrue(question.startswith("How do heat pumps work?"))
        self.assertIn("research request", question)
        self.assertNotIn("read_web_page", question, "it has no such tool: it searches by itself")
        reply = Chats(self.cfg).get(started["chat"])["messages"][-1]
        self.assertIn("They move heat rather than make it.", reply["content"])
        self.assertIn("**Sources**\n1. [Heat pump - Wikipedia](https://en.wikipedia.org/wiki/Heat_pump)", reply["content"], "the pages it drew on, as links under the answer")
        self.assertEqual((reply["agent"], reply["model"]), ("perplexity", "medium"))
        row = usage.turns(self.cfg.state_dir, 1)[0]
        self.assertEqual((row["engine"], row["model"], row["requests"], row["cost"]), ("perplexity", "medium", 1, 0.0412), "what it cost, as the service itself said")

    def test_claude_is_told_how_to_research(self):
        agent = self.make([[("text", "A report.")]])
        agent.look = lambda: ""
        started = agent.say("How do heat pumps work?", research=True)
        self.finish(agent)
        argv = self.procs[0].argv
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet", "not the quick model")
        sent = json.dumps(self.procs[0].sent)
        self.assertIn("deep research request", sent)
        self.assertIn("read_web_page", sent)
        self.assertIn("[typed] How do heat pumps work?", sent)
        self.assertEqual(Chats(self.cfg).get(started["chat"])["messages"][-1]["content"], "A report.")

    def test_if_perplexity_runs_out_claude_does_the_research(self):
        self.connect()
        agent = self.agent([[("text", "Claude's report.")]])
        self.replies = [providers.ProviderError("Perplexity has reached its limit.", limit=True, retry_at=time.time() + 3600)]
        started = agent.say("How do heat pumps work?", research=True)
        events = self.finish(agent)
        reply = Chats(self.cfg).get(started["chat"])["messages"][-1]
        self.assertIn("Claude's report.", reply["content"])
        argv = self.procs[-1].argv
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet", "not the quick model")
        self.assertTrue(any(e["k"] == "notice" for e in events), "and the owner is told who carried on")


if __name__ == "__main__":
    unittest.main()
