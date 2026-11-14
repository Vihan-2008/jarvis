"""Live reply streaming, exercised with simulated agent output. No account or model is used."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jcc import live
from jcc.jobrunner import run_process


def ev(event):
    return json.dumps({"type": "stream_event", "event": event}) + "\n"


def claude_stream(answer="Hello **there**.\nSecond line with \"quotes\"."):
    body = json.dumps({"file_path": "C:\\jobs\\x\\RESULT.md", "content": answer})
    pieces = [body[i:i + 7] for i in range(0, len(body), 7)]
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "0f8fad5b-d9cb-469f-a165-70867728950e"}) + "\n",
             ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
             ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Let me look. "}}),
             ev({"type": "content_block_stop", "index": 0}),
             ev({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": "Read", "input": {}}}),
             ev({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"file_path":"C:/p/notes.md"}'}}),
             ev({"type": "content_block_stop", "index": 1}),
             ev({"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "name": "Write", "input": {}}})]
    lines += [ev({"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": piece}}) for piece in pieces]
    lines += [ev({"type": "content_block_stop", "index": 2}),
              json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Done.",
                          "session_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
                          "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 5}}) + "\n"]
    return lines


class TestLiveFeed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-live-"))
        self.rid = "20260101-010101-abcd"
        self.cfg = SimpleNamespace(jobs_root=self.tmp, state_dir=self.tmp / "state", raw={})
        (self.tmp / self.rid).mkdir()
        self.target = self.tmp / self.rid / "live.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_claude_stream_becomes_steps_and_answer_text(self):
        answer = "Hello **there**.\nSecond line with \"quotes\" and a tab\tand é."
        feed = live.Feed("claude", self.target)
        lines = claude_stream(answer)
        for line in lines[:-4]:
            feed.line(line)
        partial = live.read(self.cfg, self.rid)
        self.assertTrue(partial["answering"])
        self.assertTrue(answer.startswith(partial["text"]) and partial["text"], partial["text"])
        for line in lines[-4:]:
            feed.line(line)
        done = live.read(self.cfg, self.rid)
        self.assertEqual(done["text"], answer)
        self.assertEqual([s["text"] for s in done["steps"]], ["Reading notes.md", "Writing the reply"])

    def test_claude_output_is_condensed_to_the_final_result(self):
        feed = live.Feed("claude", self.target)
        lines = claude_stream()
        for line in lines:
            feed.line(line)
        out = feed.output("".join(lines))
        self.assertEqual(out, lines[-1])
        from jcc.efficiency import metadata
        usage = metadata(out, "claude")
        self.assertEqual(usage["session_id"], "0f8fad5b-d9cb-469f-a165-70867728950e")
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["cached_tokens"]), (15, 20, 5))

    def test_plain_text_errors_survive(self):
        feed = live.Feed("claude", self.target)
        feed.line("Error: You've hit your usage limit. Try again in 5 hours.\n")
        self.assertIn("usage limit", feed.output("Error: You've hit your usage limit. Try again in 5 hours.\n"))

    def test_codex_events(self):
        feed = live.Feed("codex", self.target)
        for row in ({"type": "thread.started", "thread_id": "x"},
                    {"type": "item.started", "item": {"type": "command_execution", "command": "git status"}},
                    {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "src/app.py"}]}},
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "All done."}}):
            feed.line(json.dumps(row) + "\n")
        data = live.read(self.cfg, self.rid)
        self.assertEqual([s["text"] for s in data["steps"]], ["Running: git status", "Changed app.py"])
        self.assertIn("All done.", data["text"])
        raw = '{"type":"item.completed"}\n'
        self.assertEqual(feed.output(raw), raw)

    def test_secrets_never_reach_the_live_file(self):
        feed = live.Feed("codex", self.target)
        feed.line(json.dumps({"type": "item.started", "item": {"type": "command_execution",
                                                               "command": "echo gsk_abcdefghij1234567890abcd"}}) + "\n")
        self.assertNotIn("gsk_abcdefghij", self.target.read_text("utf-8"))

    def test_stream_flags_and_fallback_detection(self):
        argv = ["claude", "-p", "hi", "--output-format", "json", "--model", "sonnet"]
        self.assertEqual(live.with_stream(argv), ["claude", "-p", "hi", *live.STREAM_FLAGS, "--model", "sonnet"])
        self.assertEqual(live.with_stream(["codex", "exec"]), ["codex", "exec"])
        self.assertTrue(live.stream_rejected("error: unknown option '--include-partial-messages'"))
        self.assertFalse(live.stream_rejected("Error: You've hit your usage limit."))
        self.assertTrue(live.streaming_supported(self.cfg))
        live.mark_unsupported(self.cfg)
        self.assertFalse(live.streaming_supported(self.cfg))

    def test_bad_request_ids_are_refused(self):
        with self.assertRaises(ValueError):
            live.read(self.cfg, "../../etc")

    def test_run_process_streams_while_running(self):
        work = self.tmp / self.rid
        script = work / "agent.py"
        script.write_text("import sys,time\nfor line in open(sys.argv[1],encoding='utf-8'):\n    sys.stdout.write(line);sys.stdout.flush();time.sleep(0.01)\nsys.stderr.write('warn' + chr(10))\n", "utf-8")
        lines = claude_stream("Streamed answer.")
        (work / "stream.txt").write_text("".join(lines), "utf-8")
        env = {**__import__("os").environ, "JCC_CONTROL_FILE": str(work / "control.json"), "JCC_LIVE_PROVIDER": "claude"}
        code, out = run_process([sys.executable, str(script), str(work / "stream.txt")], work, env, 30)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(lines[-1]), out[:200])
        self.assertIn("[stderr]\nwarn", out)
        self.assertEqual(live.read(self.cfg, self.rid)["text"], "Streamed answer.")

    def test_run_process_without_live_is_unchanged(self):
        code, out = run_process([sys.executable, "-c", "print('plain out')"], self.tmp, dict(__import__("os").environ), 30)
        self.assertEqual((code, out.strip()), (0, "plain out"))


if __name__ == "__main__":
    unittest.main()
