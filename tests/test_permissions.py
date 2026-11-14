"""Permissions: how much JARVIS asks, what is waiting for a yes or no, and each answer going to the part that owns it."""
import threading
import time
import types

from jcc import assistant, job_control, permissions, policy
from jcc.vault import Vault, parse_frontmatter, render_note
from tests.test_gui import GuiTestCase

EVIL = "<img src=x onerror=alert(1)>"


class TestPermissions(GuiTestCase):
    def call(self, **body):
        return self.req("POST", "/api/permissions", body)

    def job(self, rid, **front):
        cfg = self.state.cfg
        Vault(cfg.vault).write(f"Jobs/{rid}.md", render_note({"id": rid, "status": "needs_approval", "task": "Publish the site", **front}, "# Job"))
        (cfg.jobs_root / rid).mkdir(parents=True, exist_ok=True)
        return rid

    def asking(self, rid="20261114-040401-abcd", words="May I change the deploy script?"):
        self.job(rid, asked=True)
        (self.state.cfg.jobs_root / rid / "ASKED.md").write_text(words, "utf-8")
        return rid

    def held(self, question="Shall I send this email to a@b.com?", detail="Subject: Hi", kind="send", chat="chat-1"):
        """The assistant, in the middle of a reply, holds something for a yes: the real waiting, on a thread of its own."""
        agent = self.state.assistant
        turn = types.SimpleNamespace(chat=chat, id="turn-" + chat, stopping=False)
        with agent.lock:
            agent.turns[chat] = turn
        got = {}
        waiting = threading.Thread(target=lambda: got.update(approved=agent.ask_owner(turn, question, detail, kind, timeout=20)), daemon=True)
        waiting.start()
        for _ in range(100):
            with agent.lock:
                if agent.pending:
                    break
            time.sleep(0.02)
        self.addCleanup(lambda: (agent.turns.pop(chat, None), [entry["event"].set() for entry in list(agent.pending.values())]))
        return waiting, got

    def test_the_mode_in_force_and_the_three_ways_of_asking(self):
        status, got = self.call(action="state")
        self.assertEqual((status, got["mode"], got["pending"], got["more"]), (200, "sending", [], 0))
        self.assertEqual([m["id"] for m in got["modes"]], list(policy.LEVELS), "the same three as the rules themselves go by")
        self.assertTrue(all(m["name"] and m["about"] for m in got["modes"]))

    def test_changing_the_mode_is_what_the_rules_then_go_by(self):
        self.assertEqual(self.call(action="mode", mode="all"), (200, {"mode": "all"}))
        self.assertEqual(self.call(action="state")[1]["mode"], "all")
        self.assertEqual(assistant.settings(self.state.cfg)["ask"], "all", "it is the assistant's own setting, not a second one beside it")
        for bad in ("none", "", None, ["all"], "ALL", "off"):
            self.assertEqual(self.call(action="mode", mode=bad)[0], 400, bad)
        self.assertEqual(self.call(action="state")[1]["mode"], "all", "a mode that is not one changes nothing")
        # No mode switches off what is asked about in every mode: sending still waits for a yes with the least asking.
        self.call(action="mode", mode="sending")
        ctx = policy.Context(level="sending")
        decision = policy.decide("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"}, ctx)
        self.assertTrue(policy.needs_owner(decision, ctx))

    def test_what_the_assistant_is_holding_is_listed_and_a_yes_lets_exactly_that_go_on(self):
        waiting, got = self.held(detail="Subject: Hi " + EVIL)
        status, seen = self.call(action="state")
        self.assertEqual(len(seen["pending"]), 1)
        asked = seen["pending"][0]
        self.assertEqual((asked["kind"], asked["question"], asked["detail"], asked["chat"]), ("assistant", "Shall I send this email to a@b.com?", "Subject: Hi " + EVIL, "chat-1"))
        self.assertIn("other people", asked["why"])
        self.assertEqual(self.call(action="decide", kind="assistant", id="made-up", yes=True)[0], 400, "a question that is not waiting cannot be answered")
        self.assertIsNone(got.get("approved"), "and nothing was let through by trying")
        self.assertEqual(self.call(action="decide", kind="assistant", id=asked["id"], yes=True), (200, {"kind": "assistant", "id": asked["id"], "answered": "yes"}))
        waiting.join(5)
        self.assertIs(got["approved"], True)
        self.assertEqual(self.call(action="state")[1]["pending"], [], "answered: it is no longer waiting")
        self.assertEqual(self.call(action="decide", kind="assistant", id=asked["id"], yes=True)[0], 400, "an answer is taken once")

    def test_a_no_and_anything_that_is_not_plainly_yes_let_nothing_through(self):
        for answer in (False, "true", 1, None):
            waiting, got = self.held(chat="chat-" + str(answer))
            ident = self.call(action="state")[1]["pending"][0]["id"]
            self.assertEqual(self.call(action="decide", kind="assistant", id=ident, yes=answer)[0], 200)
            waiting.join(5)
            self.assertIs(got["approved"], False, answer)

    def test_a_job_that_asks_is_answered_once_and_only_for_the_question_shown(self):
        rid = self.asking()
        asked = self.call(action="state")[1]["pending"]
        self.assertEqual([(a["kind"], a["id"], a["detail"], a["title"]) for a in asked], [("job", rid, "May I change the deploy script?", "Publish the site")])
        mark = asked[0]["mark"]
        self.assertEqual(mark, job_control.asked(self.state.cfg, rid)["mark"])
        self.assertEqual(self.call(action="decide", kind="job", id=rid, yes=True, text="Yes."), (400, {"error": "Read the job's question again before you answer."}))
        # The window has not caught up: the job has moved on to another question.
        (self.state.cfg.jobs_root / rid / "ASKED.md").write_text("May I ALSO delete the old logs?", "utf-8")
        status, said = self.call(action="decide", kind="job", id=rid, yes=True, text="Yes.", mark=mark)
        self.assertEqual((status, said["error"]), (400, "This job is asking something else now. Read its question again before you answer."))
        self.assertEqual(parse_frontmatter(Vault(self.state.cfg.vault).read(f"Jobs/{rid}.md"))[0]["status"], "needs_approval", "nothing was answered")
        fresh = self.call(action="state")[1]["pending"][0]
        self.assertEqual(fresh["detail"], "May I ALSO delete the old logs?")
        status, done = self.call(action="decide", kind="job", id=rid, yes=True, text="Yes, those too.", mark=fresh["mark"])
        self.assertEqual((status, done), (200, {"kind": "job", "id": rid, "status": "queued", "answered": "yes"}))
        self.assertEqual(job_control.signal(self.state.cfg.jobs_root / rid), "resume", "the same job carries on")
        self.assertEqual(self.call(action="state")[1]["pending"], [])
        self.assertEqual(self.call(action="decide", kind="job", id=rid, yes=True, mark=fresh["mark"])[0], 400, "an answer is taken once")

    def test_a_no_to_a_job_ends_it_and_needs_no_mark(self):
        rid = self.asking("20261114-040402-abcd")
        self.assertEqual(self.call(action="decide", kind="job", id=rid, yes=False, text="Not on this server."), (200, {"kind": "job", "id": rid, "status": "cancelled", "answered": "no"}))
        self.assertEqual(self.call(action="state")[1]["pending"], [])

    def test_a_change_that_waits_to_be_looked_at_is_listed_but_never_decided_here(self):
        rid = self.job("20261114-040403-abcd")
        (self.state.cfg.jobs_root / rid / "repo").mkdir()                      # a copy with a change in it: a review, not a question
        blocked = self.job("20261114-040404-abcd", blocked_by="keys/secrets")   # something a job may never do by itself: nothing to decide
        asked = self.call(action="state")[1]["pending"]
        self.assertEqual([(a["kind"], a["id"]) for a in asked], [("review", rid)])
        self.assertNotIn(blocked, str(asked))
        status, said = self.call(action="decide", kind="review", id=rid, yes=True)
        self.assertEqual((status, said["error"]), (400, "Look at the change first: open it, then approve it there."))
        self.assertEqual(parse_frontmatter(Vault(self.state.cfg.vault).read(f"Jobs/{rid}.md"))[0]["status"], "needs_approval")

    def test_everything_that_waits_is_in_one_list_oldest_question_first(self):
        self.held(question="Shall I run this command?", detail="dir", kind="risky")
        rid = self.asking("20261114-040405-abcd")
        review = self.job("20261114-040406-abcd")
        (self.state.cfg.jobs_root / review / "repo").mkdir()
        kinds = [a["kind"] for a in self.call(action="state")[1]["pending"]]
        self.assertEqual(sorted(kinds), ["assistant", "job", "review"])
        self.assertEqual(kinds[0], "assistant", "what holds up a reply in progress comes first")

    def test_only_so_many_are_listed_and_the_rest_are_counted(self):
        keep = permissions.MOST
        permissions.MOST = 2
        try:
            for n in range(4):
                self.asking(f"20261114-0405{n:02d}-abcd")
            got = self.call(action="state")[1]
            self.assertEqual((len(got["pending"]), got["more"]), (2, 2))
        finally:
            permissions.MOST = keep

    def test_what_is_refused(self):
        for body in ({"action": "dance"}, {"action": "decide", "kind": "nonsense", "id": "x", "yes": True}, {"action": "decide", "kind": "job", "id": "../../x", "yes": False},
                     {"action": "decide", "kind": "job", "id": "20200101-000000-abcd", "yes": False}, {"action": "decide"}):
            status, said = self.call(**body)
            self.assertEqual(status, 400, body)
            self.assertNotIn("Traceback", str(said))
        self.assertEqual(self.req("POST", "/api/permissions", {"action": "state"}, token=False)[0], 401, "only this app's own window may ask")
        self.assertEqual(self.req("POST", "/api/permissions", {"action": "mode", "mode": "all"}, token=False)[0], 401)
        self.assertEqual(self.req("POST", "/api/permissions", {"action": "state"}, origin="https://evil.example")[0], 403, "no other website")


if __name__ == "__main__":
    import unittest
    unittest.main()
