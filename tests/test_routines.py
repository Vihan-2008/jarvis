"""Routines: their schedules, the ticker that starts their runs (once, never in a burst, never on top of a run that is
still going), what their owner can do with them, and the address the window uses."""
import json
import threading
import time
import types

from jcc import config, dashboard
from jcc import routines as rt
from jcc.gui import GuiState
from jcc.vault import render_note
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


def at(year, month, day, hour=0, minute=0):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


MONDAY = at(2026, 11, 16, 9, 0)               # Monday 16 November 2026, 09:00 local time
SECRET = "sk-ant-api03-" + "a" * 90
EVERY_HOUR = {"kind": "every", "minutes": 60}


class Send:
    """Stands in for the app's routine_send: writes down what it was given and hands back a job and a chat."""

    def __init__(self, fail=None, pause=0.0):
        self.sent, self.fail, self.pause = [], fail, pause
        self.lock = threading.Lock()

    def __call__(self, routine):
        with self.lock:
            self.sent.append(routine)
            n = len(self.sent)
        time.sleep(self.pause)
        if self.fail:
            raise self.fail
        return {"job": f"20261116-{n:06d}-abcd", "chat": "20261116-090000-cafe"}


class RoutineTestCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (self.vault / "Jobs").mkdir(exist_ok=True)
        self.cfg.projects["calc"] = types.SimpleNamespace(key="calc", name="Calculator", path=self.tmp / "calc")
        rt._sending.clear()

    def make(self, schedule=EVERY_HOUR, now=MONDAY, **more):
        return rt.save(self.cfg, {"name": "Calendar", "what": "Tell me what is on my calendar today.", "schedule": schedule, **more}, now=now)

    def job(self, rid, status, **fm):
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": status, **fm}, "# Job"), "utf-8")

    def saved(self, ident):
        return next(r for r in json.loads((self.cfg.state_dir / "routines" / "routines.json").read_text("utf-8"))["routines"] if r["id"] == ident)

    def rewrite(self, ident, **fields):
        path = self.cfg.state_dir / "routines" / "routines.json"
        data = json.loads(path.read_text("utf-8"))
        next(r for r in data["routines"] if r["id"] == ident).update(fields)
        path.write_text(json.dumps(data), "utf-8")


class TestSchedules(EngineTestCase):
    def test_every_so_many_minutes_lands_on_fixed_times_and_never_drifts(self):
        two_hours = {"kind": "every", "minutes": 120}
        self.assertEqual(rt.next_slot(two_hours, at(2026, 11, 16, 9, 30)), at(2026, 11, 16, 10, 0))
        self.assertEqual(rt.next_slot(two_hours, at(2026, 11, 16, 10, 0)), at(2026, 11, 16, 12, 0), "never the moment itself")
        self.assertEqual(rt.next_slot(two_hours, at(2026, 11, 16, 10, 0) + 19), at(2026, 11, 16, 12, 0), "a late tick does not move the next slot")
        self.assertEqual(rt.next_slot({"kind": "every", "minutes": 5}, at(2026, 11, 16, 9, 2)), at(2026, 11, 16, 9, 5))

    def test_every_day_at_a_time_later_today_or_tomorrow(self):
        eight = {"kind": "daily", "at": "08:00"}
        self.assertEqual(rt.next_slot(eight, at(2026, 11, 16, 7, 0)), at(2026, 11, 16, 8, 0))
        self.assertEqual(rt.next_slot(eight, at(2026, 11, 16, 9, 0)), at(2026, 11, 17, 8, 0), "a time that has already passed today is tomorrow")
        self.assertEqual(rt.next_slot(eight, at(2026, 11, 16, 8, 0)), at(2026, 11, 17, 8, 0))
        self.assertEqual(rt.next_slot(eight, at(2026, 11, 30, 9, 0)), at(2026, 12, 1, 8, 0), "over the end of a month")

    def test_chosen_weekdays(self):
        monday_and_thursday = {"kind": "daily", "at": "17:30", "days": [3, 0]}
        self.assertEqual(rt.next_slot(monday_and_thursday, at(2026, 11, 14, 12, 0)), at(2026, 11, 16, 17, 30), "Saturday: the next Monday")
        self.assertEqual(rt.next_slot(monday_and_thursday, at(2026, 11, 16, 18, 0)), at(2026, 11, 19, 17, 30), "Monday evening: Thursday")
        self.assertEqual(rt.next_slot(monday_and_thursday, at(2026, 11, 19, 17, 30)), at(2026, 11, 23, 17, 30))
        self.assertEqual(rt.check_schedule({"kind": "daily", "at": "17:30", "days": list(range(7))})["days"], [], "every day ticked is every day")

    def test_midnight(self):
        self.assertEqual(rt.next_slot({"kind": "daily", "at": "00:00"}, at(2026, 11, 16, 23, 59)), at(2026, 11, 17, 0, 0))
        self.assertEqual(rt.next_slot({"kind": "every", "minutes": 1440}, at(2026, 11, 16, 23, 59)), at(2026, 11, 17, 0, 0))
        self.assertEqual(rt.next_slot({"kind": "every", "minutes": 10080}, at(2026, 11, 16, 0, 0)), at(2026, 11, 23, 0, 0), "a week: Monday at midnight")

    def test_bad_schedules_are_refused_with_a_sentence(self):
        for bad in (None, "daily", {}, {"kind": "hourly"}, {"kind": "every", "minutes": 4}, {"kind": "every", "minutes": 10081},
                    {"kind": "every", "minutes": "60"}, {"kind": "every", "minutes": True}, {"kind": "every", "minutes": 60.5},
                    {"kind": "daily", "at": "24:00"}, {"kind": "daily", "at": "8:00"}, {"kind": "daily", "at": "08:60"}, {"kind": "daily", "at": "08:00\n"},
                    {"kind": "daily", "at": "08:00", "days": [7]}, {"kind": "daily", "at": "08:00", "days": ["mon"]}, {"kind": "daily", "at": "08:00", "days": "0"}):
            with self.assertRaises(rt.RoutineError, msg=bad) as said:
                rt.check_schedule(bad)
            self.assertTrue(str(said.exception).endswith("."), said.exception)

    def test_a_schedule_in_plain_words(self):
        for schedule, words in (({"kind": "every", "minutes": 120}, "Every 2 hours"), ({"kind": "every", "minutes": 60}, "Every hour"),
                                ({"kind": "every", "minutes": 45}, "Every 45 minutes"), ({"kind": "every", "minutes": 2880}, "Every 2 days"),
                                ({"kind": "every", "minutes": 10080}, "Every week"), ({"kind": "daily", "at": "08:00"}, "Every day at 08:00"),
                                ({"kind": "daily", "at": "17:30", "days": [0, 3]}, "Mondays and Thursdays at 17:30"),
                                ({"kind": "daily", "at": "07:15", "days": [0, 2, 4]}, "Mondays, Wednesdays and Fridays at 07:15"),
                                ({"kind": "daily", "at": "09:00", "days": [0, 1, 2, 3, 4]}, "Weekdays at 09:00"), ({"kind": "daily", "at": "10:00", "days": [6]}, "Sundays at 10:00"),
                                ({"kind": "nonsense"}, "Not set")):
            self.assertEqual(rt.in_words(schedule), words)


class TestTheTicker(RoutineTestCase):
    def test_a_due_slot_is_fired_once_and_the_next_one_is_set(self):
        made = self.make()
        self.assertEqual(made["next"], at(2026, 11, 16, 10, 0))
        send = Send()
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 9, 59)), [], "not due yet")
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0) + 7), [made["id"]])
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0) + 27), [], "the same slot, a tick later")
        self.assertEqual(len(send.sent), 1)
        self.assertEqual(send.sent[0]["what"], "Tell me what is on my calendar today.")
        saved = self.saved(made["id"])
        self.assertEqual(saved["next"], at(2026, 11, 16, 11, 0))
        self.assertEqual((saved["last"]["slot"], saved["last"]["job"], saved["last"]["status"]), (at(2026, 11, 16, 10, 0), "20261116-000001-abcd", "started"))
        self.assertEqual(saved["chat"], "20261116-090000-cafe", "the chat it was sent in is kept for every later run")

    def test_the_slot_is_written_down_before_the_run_is_started(self):
        made = self.make()
        seen = []
        rt.tick(self.cfg, lambda routine: seen.append(self.saved(made["id"])) or {"job": "20261116-100000-abcd", "chat": ""}, now=at(2026, 11, 16, 10, 0))
        self.assertEqual((seen[0]["last"]["status"], seen[0]["last"]["slot"], seen[0]["next"]), ("starting", at(2026, 11, 16, 10, 0), at(2026, 11, 16, 11, 0)))

    def test_a_slot_is_fired_once_even_when_two_tickers_race(self):
        made = self.make()
        send = Send(pause=0.2)
        start = threading.Barrier(4)
        fired = []

        def ticker():
            start.wait()
            fired.extend(rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0) + 1))
        threads = [threading.Thread(target=ticker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual((len(send.sent), fired), (1, [made["id"]]))
        self.assertEqual(len(self.saved(made["id"])["runs"]), 1)

    def test_a_second_process_that_finds_the_slot_written_down_leaves_it(self):
        made = self.make()
        send = Send()
        rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0))
        rt._sending.clear()                                    # (another process knows nothing of this one)
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0) + 3), [])
        # Even one that read the file before it was saved, and so thinks the slot is still to come, finds it written down.
        self.rewrite(made["id"], next=at(2026, 11, 16, 10, 0))
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0) + 5), [])
        self.assertEqual(len(send.sent), 1)
        self.assertEqual(self.saved(made["id"])["next"], at(2026, 11, 16, 11, 0))

    def test_after_the_app_was_off_one_run_is_started_for_the_latest_missed_slot(self):
        made = self.make()
        send = Send()
        later = at(2026, 11, 16, 19, 25)                       # ten slots missed
        self.assertEqual(rt.tick(self.cfg, send, now=later), [made["id"]])
        self.assertEqual(rt.tick(self.cfg, send, now=later + 20), [])
        saved = self.saved(made["id"])
        self.assertEqual(len(send.sent), 1, "never a burst")
        self.assertEqual((saved["last"]["slot"], saved["next"]), (at(2026, 11, 16, 19, 0), at(2026, 11, 16, 20, 0)))
        daily = self.make({"kind": "daily", "at": "08:00"})
        rt.tick(self.cfg, send, now=at(2026, 11, 20, 12, 0))      # four days off
        saved = self.saved(daily["id"])
        self.assertEqual((saved["last"]["slot"], saved["next"]), (at(2026, 11, 20, 8, 0), at(2026, 11, 21, 8, 0)))

    def test_a_slot_that_comes_while_the_last_run_is_still_going_is_skipped(self):
        made = self.make()
        send = Send()
        rt.tick(self.cfg, send, now=at(2026, 11, 16, 10, 0))
        for n, status in enumerate(("running", "queued", "paused", "needs_approval"), start=1):
            self.job("20261116-000001-abcd", status)
            due = at(2026, 11, 16, 10 + n, 0)
            self.assertEqual(rt.tick(self.cfg, send, now=due), [], status)
            saved = self.saved(made["id"])
            self.assertEqual((saved["last"]["slot"], saved["last"]["status"], saved["last"]["note"]), (due, "skipped", "Skipped: the last run is still going."))
            self.assertEqual(saved["next"], due + 3600, "and the routine moves on")
        self.assertEqual(len(send.sent), 1, "no pile-up")
        self.job("20261116-000001-abcd", "done")
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 15, 0)), [made["id"]])

    def test_a_run_that_never_started_is_marked_failed_and_not_started_again_by_itself(self):
        made = self.make()
        self.rewrite(made["id"], runs=[{"slot": MONDAY, "started": MONDAY, "job": "", "status": "starting", "note": ""}])
        send = Send()
        self.assertEqual(rt.get(self.cfg, made["id"], now=MONDAY + 60)["state"], "running", "within two minutes it may just be slow")
        rt.tick(self.cfg, send, now=MONDAY + 121)
        saved = self.saved(made["id"])
        self.assertEqual((saved["runs"][0]["status"], saved["runs"][0]["note"]), ("failed", "It did not start: the app was closed just then."))
        self.assertEqual(send.sent, [], "it is not started again by itself")
        shown = rt.get(self.cfg, made["id"], now=MONDAY + 130)
        self.assertEqual((shown["state"], shown["can_retry"]), ("failed", True), "its owner can press Retry")

    def test_a_run_being_started_in_this_process_is_not_taken_as_never_started(self):
        made = self.make()
        rt._sending.add((made["id"], MONDAY))
        self.rewrite(made["id"], runs=[{"slot": MONDAY, "started": MONDAY, "job": "", "status": "starting", "note": ""}])
        rt.tick(self.cfg, Send(), now=MONDAY + 300)
        self.assertEqual(self.saved(made["id"])["runs"][0]["status"], "starting")

    def test_a_run_that_cannot_be_started_says_why_and_the_routine_carries_on(self):
        made = self.make()
        rt.tick(self.cfg, Send(fail=ValueError("A message is being sent. Key " + SECRET)), now=at(2026, 11, 16, 10, 0))
        saved = self.saved(made["id"])
        self.assertEqual(saved["last"]["status"], "failed")
        self.assertTrue(saved["last"]["note"].startswith("It could not be started: A message is being sent."))
        self.assertNotIn(SECRET, json.dumps(saved))
        rt.tick(self.cfg, Send(fail=RuntimeError("boom " + SECRET)), now=at(2026, 11, 16, 11, 0))
        self.assertEqual(self.saved(made["id"])["last"]["note"], "It could not be started: something went wrong (RuntimeError)")
        send = Send()
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 12, 0)), [made["id"]], "it carries on at its next slot")
        rt.tick(self.cfg, lambda routine: {"job": "../../x", "chat": "c"}, now=at(2026, 11, 16, 13, 0))
        self.assertEqual(self.saved(made["id"])["last"]["status"], "failed", "a run with no proper job is not taken as started")

    def test_after_five_failures_in_a_row_it_pauses_itself_and_says_so(self):
        made = self.make()
        broken = Send(fail=ValueError("No agent is available."))
        for hour in range(10, 15):
            rt.tick(self.cfg, broken, now=at(2026, 11, 16, hour, 0))
        saved = self.saved(made["id"])
        self.assertEqual((saved["enabled"], saved["next"], saved["last"]["note"]), (False, None, "Paused after 5 runs in a row failed."))
        self.assertEqual(rt.tick(self.cfg, broken, now=at(2026, 11, 16, 16, 0)), [])
        self.assertEqual(len(broken.sent), 5)
        self.assertEqual(rt.get(self.cfg, made["id"], now=at(2026, 11, 16, 16, 0))["state"], "paused")
        rt.resume(self.cfg, made["id"], now=at(2026, 11, 16, 16, 30))
        send = Send()
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 17, 0)), [made["id"]], "resumed, the old failures are not held against it")

    def test_jobs_that_fail_five_times_in_a_row_pause_it_too(self):
        made = self.make()
        send = Send()
        for hour in range(10, 15):
            rt.tick(self.cfg, send, now=at(2026, 11, 16, hour, 0))
            self.job(send.sent and f"20261116-{len(send.sent):06d}-abcd", "failed")
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 15, 0)), [])
        self.assertEqual((self.saved(made["id"])["enabled"], len(send.sent)), (False, 5))

    def test_a_paused_routine_does_not_run_and_resumes_from_the_next_slot_to_come(self):
        made = self.make()
        rt.pause(self.cfg, made["id"])
        send = Send()
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 15, 0)), [])
        self.assertEqual(self.saved(made["id"])["next"], None)
        resumed = rt.resume(self.cfg, made["id"], now=at(2026, 11, 16, 15, 10))
        self.assertEqual(resumed["next"], at(2026, 11, 16, 16, 0), "nothing is made up for the time it was paused")
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 15, 30)), [])
        self.assertEqual(rt.tick(self.cfg, send, now=at(2026, 11, 16, 16, 0)), [made["id"]])

    def test_a_damaged_file_does_not_stop_anything(self):
        folder = self.cfg.state_dir / "routines"
        folder.mkdir(parents=True)
        (folder / "routines.json").write_text("{not json", "utf-8")
        self.assertEqual(rt.tick(self.cfg, Send(), now=MONDAY), [])
        self.assertEqual(rt.listing(self.cfg, MONDAY), [])
        self.assertEqual((folder / "routines.damaged.json").read_text("utf-8"), "{not json", "what was there is kept aside")
        made = self.make()
        self.assertEqual([r["id"] for r in rt.listing(self.cfg, MONDAY)], [made["id"]])
        (folder / "routines.json").write_text(json.dumps({"routines": [{"id": "../../x"}, "odd", {"id": "rt-20261116-090000-abcd", "enabled": True, "next": 1, "schedule": "odd"}]}), "utf-8")
        self.assertEqual(rt.tick(self.cfg, Send(), now=MONDAY), [], "a routine that cannot be understood is passed over")
        self.assertEqual([r["id"] for r in rt.listing(self.cfg, MONDAY)], ["rt-20261116-090000-abcd"])


class TestWhatTheOwnerDoes(RoutineTestCase):
    def test_a_routine_is_made_and_changed_and_a_new_schedule_sets_its_next_run(self):
        agent = next(iter(self.cfg.agents))
        made = self.make(project="calc", mode="build", agent=agent)
        self.assertRegex(made["id"], r"^rt-\d{8}-\d{6}-[0-9a-f]{4}$")
        self.assertEqual((made["project"], made["mode"], made["agent"], made["enabled"], made["chat"], made["runs"]), ("calc", "build", agent, True, "", []))
        changed = rt.save(self.cfg, {"id": made["id"], "name": "Tests", "what": "Run the tests and fix what fails.", "project": "calc", "mode": "build",
                                     "schedule": {"kind": "daily", "at": "17:30", "days": [0, 3]}}, now=MONDAY)
        self.assertEqual((changed["id"], changed["name"], changed["next"]), (made["id"], "Tests", at(2026, 11, 16, 17, 30)))
        same = rt.save(self.cfg, {**changed, "name": "Tests again"}, now=MONDAY + 3600)
        self.assertEqual(same["next"], at(2026, 11, 16, 17, 30), "the same schedule keeps its next run")
        self.assertEqual(len(rt.listing(self.cfg, MONDAY)), 1)

    def test_what_is_refused(self):
        agent = next(iter(self.cfg.agents))
        good = {"name": "Calendar", "what": "Tell me my day.", "schedule": EVERY_HOUR}
        for bad, words in (({"name": ""}, "name"), ({"name": "x" * 81}, "name"), ({"what": "hi"}, "request"), ({"what": "x" * 4001}, "request"),
                           ({"project": "no-such"}, "projects"), ({"project": "../calc"}, "projects"), ({"mode": "build"}, "needs a project"),
                           ({"mode": "delete"}, "Choose"), ({"agent": "someone-else"}, "agents"), ({"schedule": {"kind": "every", "minutes": 1}}, "5 minutes")):
            with self.assertRaises(rt.RoutineError, msg=bad) as said:
                rt.save(self.cfg, {**good, **bad}, now=MONDAY)
            self.assertIn(words, str(said.exception))
        self.assertEqual(rt.save(self.cfg, {**good, "agent": agent}, now=MONDAY)["agent"], agent)
        for ident in ("../../x", "rt-20261116-090000-zzzz", "rt-20261116-090000-abcd", 7, ["x"]):
            for act in (rt.pause, rt.remove, lambda cfg, i: rt.get(cfg, i), lambda cfg, i: rt.save(cfg, {**good, "id": i})):
                with self.assertRaises(rt.RoutineError, msg=ident):
                    act(self.cfg, ident)

    def test_secrets_in_the_request_are_hidden_before_it_is_saved(self):
        made = self.make(what="Deploy with the key " + SECRET + " every hour.")
        self.assertNotIn(SECRET, made["what"])
        self.assertNotIn(SECRET, (self.cfg.state_dir / "routines" / "routines.json").read_text("utf-8"))

    def test_no_more_than_fifty(self):
        for _ in range(50):
            self.make()
        with self.assertRaises(rt.RoutineError) as said:
            self.make()
        self.assertIn("50 routines", str(said.exception))

    def test_run_now_starts_one_run_at_once_and_not_on_top_of_one_that_is_going(self):
        made = self.make()
        send = Send()
        shown = rt.run_now(self.cfg, made["id"], send, now=MONDAY + 60)
        self.assertEqual((len(send.sent), shown["next"], shown["last"]["manual"]), (1, made["next"], True), "when it runs next is not changed")
        self.assertEqual(shown["state"], "running")
        with self.assertRaises(rt.RoutineError) as said:
            rt.run_now(self.cfg, made["id"], send, now=MONDAY + 90)
        self.assertIn("still going", str(said.exception))
        self.job("20261116-000001-abcd", "done")
        rt.run_now(self.cfg, made["id"], send, now=MONDAY + 120)
        self.assertEqual(len(send.sent), 2)

    def test_cancel_stops_the_run_through_the_jobs_own_controls(self):
        made = self.make()
        rt.run_now(self.cfg, made["id"], Send(), now=MONDAY)
        self.job("20261116-000001-abcd", "running")
        stopped = []
        got = rt.cancel(self.cfg, made["id"], lambda cfg, job, action: stopped.append((job, action)), now=MONDAY + 5)
        self.assertEqual((stopped, got["said"], got["last"]["state"]), ([("20261116-000001-abcd", "cancel")], "The run was cancelled.", "cancelled"))
        with self.assertRaises(rt.RoutineError):
            rt.cancel(self.cfg, made["id"], lambda *a: None, now=MONDAY + 6)

    def test_cancelling_a_run_that_has_just_ended_says_so(self):
        made = self.make()
        rt.run_now(self.cfg, made["id"], Send(), now=MONDAY)
        self.job("20261116-000001-abcd", "running")

        def ended(cfg, job, action):
            raise ValueError("This job cannot be controlled in its current state.")
        self.assertEqual(rt.cancel(self.cfg, made["id"], ended, now=MONDAY + 5)["said"], "It had already ended.")

        def other(cfg, job, action):
            raise ValueError("The worker is still stopping. Try again in a moment.")
        with self.assertRaises(rt.RoutineError) as said:
            rt.cancel(self.cfg, made["id"], other, now=MONDAY + 6)
        self.assertIn("still stopping", str(said.exception))

    def test_the_real_job_controls_cancel_a_run_that_waits_for_its_owner(self):
        made = self.make()
        rt.run_now(self.cfg, made["id"], Send(), now=MONDAY)
        self.job("20261116-000001-abcd", "needs_approval")
        self.assertEqual(rt.cancel(self.cfg, made["id"], now=MONDAY + 5)["said"], "The run was cancelled.")
        self.assertIn('status: "cancelled"', (self.vault / "Jobs" / "20261116-000001-abcd.md").read_text("utf-8"))

    def test_retry_only_after_a_run_failed_was_cancelled_or_did_not_start(self):
        made = self.make()
        send = Send()
        with self.assertRaises(rt.RoutineError):
            rt.retry(self.cfg, made["id"], send, now=MONDAY)      # it has never run
        rt.run_now(self.cfg, made["id"], send, now=MONDAY)
        with self.assertRaises(rt.RoutineError):
            rt.retry(self.cfg, made["id"], send, now=MONDAY + 5)  # it is going
        self.job("20261116-000001-abcd", "done")
        with self.assertRaises(rt.RoutineError):
            rt.retry(self.cfg, made["id"], send, now=MONDAY + 10)  # it went well
        self.job("20261116-000001-abcd", "failed")
        self.assertTrue(rt.get(self.cfg, made["id"], now=MONDAY + 11)["can_retry"])
        again = rt.retry(self.cfg, made["id"], send, now=MONDAY + 12)
        self.assertEqual((len(send.sent), len(again["runs"]), again["last"]["job"]), (2, 2, "20261116-000002-abcd"), "a new run of its own")

    def test_a_run_reads_its_state_from_its_job_note(self):
        made = self.make()
        rt.run_now(self.cfg, made["id"], Send(), now=MONDAY)
        self.assertEqual(rt.get(self.cfg, made["id"], now=MONDAY + 60)["last"]["state"], "starting", "no note yet")
        self.assertEqual(rt.get(self.cfg, made["id"], now=MONDAY + 601)["last"]["state"], "failed", "no note after ten minutes")
        for status, state, word in (("queued", "running", "running"), ("running", "running", "running"), ("paused", "waiting", "waiting"),
                                    ("needs_approval", "waiting", "waiting"), ("failed", "failed", "failed"), ("cancelled", "cancelled", "failed"), ("done", "done", "done")):
            self.job("20261116-000001-abcd", status)
            shown = rt.get(self.cfg, made["id"], now=MONDAY + 60)
            self.assertEqual((shown["last"]["state"], shown["state"]), (state, word), status)
            self.assertEqual(shown["can_cancel"], word in ("running", "waiting"))
        rt.pause(self.cfg, made["id"])
        self.assertEqual(rt.get(self.cfg, made["id"], now=MONDAY + 60)["state"], "paused")
        self.assertEqual(rt.get(self.cfg, self.make()["id"], now=MONDAY)["state"], "scheduled")

    def test_removed_is_gone(self):
        made = self.make()
        rt.remove(self.cfg, made["id"])
        self.assertEqual(rt.listing(self.cfg, MONDAY), [])
        with self.assertRaises(rt.RoutineError):
            rt.remove(self.cfg, made["id"])


class TestTheAgentsPanel(RoutineTestCase):
    def test_routines_that_are_on_are_scheduled_soonest_first_and_their_jobs_say_so(self):
        later = self.make({"kind": "daily", "at": "23:00"}, name="Late <b>one</b>")
        sooner = self.make({"kind": "every", "minutes": 5})
        rt.pause(self.cfg, self.make()["id"])
        got = dashboard.overview(self.cfg)
        self.assertEqual([(r["kind"], r["id"], r["state"]) for r in got["scheduled"]], [("routine", sooner["id"], "scheduled"), ("routine", later["id"], "scheduled")])
        self.assertEqual((got["scheduled"][1]["title"], got["scheduled"][1]["doing"]), ("Late <b>one</b>", "Every day at 23:00"))
        self.rewrite(later["id"], chat="20261116-090000-cafe")
        self.job("20261116-100000-abcd", "failed", chat_id="20261116-090000-cafe", task="Tell me my day")
        self.job("20261116-100001-abcd", "running", chat_id="20261116-090000-beef", task="Something else")
        got = dashboard.overview(self.cfg)
        self.assertEqual([(r["id"], r["state"], r.get("routine")) for r in got["recent"]], [("20261116-100000-abcd", "failed", "Late <b>one</b>")], "a failed job is shown as failed")
        self.assertNotIn("routine", got["working"][0])


class TestTheAppsOwnSend(EngineTestCase):
    def test_a_routine_is_sent_in_its_own_chat_as_a_typed_message_and_the_chat_is_reused(self):
        state = GuiState(config.load(), {"transport": self.transport, "spawner": lambda argv, cwd, env: self.spawned.append(argv) or 1})
        routine = {"id": "rt-20261116-090000-abcd", "name": "Calendar", "what": "Tell me what is on my calendar today.", "project": "", "mode": "ask", "agent": "auto", "chat": ""}
        first = state.routine_send(routine)
        self.assertRegex(first["job"], r"^\d{8}-\d{6}-[0-9a-f]{4}$")
        from jcc.chats import Chats
        chat = Chats(state.cfg).get(first["chat"])
        self.assertEqual(chat["title"], "Routine: Calendar")
        self.assertEqual([m["content"] for m in chat["messages"] if m["role"] == "user"], ["Tell me what is on my calendar today."])
        second = state.routine_send({**routine, "chat": first["chat"]})
        self.assertEqual(second["chat"], first["chat"])
        self.assertNotEqual(second["job"], first["job"])
        lost = state.routine_send({**routine, "chat": "20200101-000000-dead"})
        self.assertNotEqual(lost["chat"], first["chat"], "a chat that is gone is made afresh")


class TestTheAddress(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.state.cfg.projects["calc"] = types.SimpleNamespace(key="calc", name="Calculator", path=self.tmp / "calc")
        self.sent = Send()
        self.state.routine_send = self.sent
        rt._sending.clear()

    def call(self, **body):
        return self.req("POST", "/api/routines", body)

    def test_every_action_over_the_wire(self):
        status, got = self.call(action="list")
        self.assertEqual((status, got["routines"]), (200, []))
        self.assertIn({"key": "calc", "name": "Calculator"}, got["projects"])
        self.assertEqual(got["agents"], [n for n, a in self.state.cfg.agents.items() if a.enabled])
        status, got = self.call(action="save", routine={"name": "Tests", "what": "Run the tests and fix what fails.", "project": "calc", "mode": "build",
                                                        "schedule": {"kind": "every", "minutes": 120}})
        self.assertEqual((status, got["said"], got["routines"][0]["in_words"], got["routines"][0]["state"]), (200, "Saved.", "Every 2 hours", "scheduled"))
        ident = got["routines"][0]["id"]
        status, got = self.call(action="run", id=ident)
        self.assertEqual((status, got["routines"][0]["state"], len(self.sent.sent)), (200, "running", 1))
        self.assertEqual(self.call(action="run", id=ident)[0], 400, "not on top of a run that is going")
        self.assertEqual(self.call(action="retry", id=ident)[0], 400)
        (self.vault / "Jobs").mkdir(exist_ok=True)
        (self.vault / "Jobs" / "20261116-000001-abcd.md").write_text(render_note({"id": "20261116-000001-abcd", "status": "needs_approval"}, "# Job"), "utf-8")
        status, got = self.call(action="cancel", id=ident)
        self.assertEqual((status, got["said"], got["routines"][0]["can_retry"]), (200, "The run was cancelled.", True))
        status, got = self.call(action="retry", id=ident)
        self.assertEqual((status, len(self.sent.sent)), (200, 2))
        status, got = self.call(action="pause", id=ident)
        self.assertEqual((status, got["routines"][0]["enabled"], got["routines"][0]["next"]), (200, False, None))
        status, got = self.call(action="resume", id=ident)
        self.assertEqual((status, got["routines"][0]["enabled"]), (200, True))
        self.assertGreater(got["routines"][0]["next"], time.time())
        status, got = self.call(action="remove", id=ident)
        self.assertEqual((status, got["routines"]), (200, []))

    def test_what_is_refused_over_the_wire(self):
        good = {"name": "Tests", "what": "Run the tests.", "schedule": {"kind": "every", "minutes": 60}}
        for body in ({"action": "save", "routine": {**good, "project": "no-such"}}, {"action": "save", "routine": {**good, "mode": "build"}},
                     {"action": "save", "routine": {**good, "schedule": {"kind": "every", "minutes": 1}}}, {"action": "save", "routine": "x"},
                     {"action": "save"}, {"action": "pause", "id": "../../x"}, {"action": "run", "id": "rt-20261116-090000-abcd"},
                     {"action": "cancel", "id": None}, {"action": "dance"}):
            status, said = self.call(**body)
            self.assertEqual(status, 400, body)
            self.assertIsInstance(said.get("error"), str)
            self.assertNotIn("Traceback", json.dumps(said))
        self.assertEqual(self.req("POST", "/api/routines", {"action": "list"}, token=False)[0], 401, "only this app's own window may ask")
        self.assertEqual(self.sent.sent, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
