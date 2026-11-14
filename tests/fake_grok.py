"""A stand-in for Grok's command-line agent, for tests. It answers in the shape the real one was seen to answer in
(one piece of JSON; exit code 0 even when it stopped because something was refused).

What it does is chosen with FAKE_GROK_MODE: "ok" (makes a small change and finishes), "refused" (makes its change,
then says it was refused something and stops, as a run with no window does), "nothing" (finishes without a change).
What it was started with is written to grok-argv.json beside the job's folder, for the test to read.
"""
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
cwd = Path(argv[argv.index("--cwd") + 1]) if "--cwd" in argv else Path.cwd()
mode = os.environ.get("FAKE_GROK_MODE", "ok")
(cwd.parent / "grok-argv.json").write_text(json.dumps(argv), "utf-8")
if mode in ("ok", "refused"):
    target = cwd / "src" / "pkg" / "__init__.py"
    target.write_text(target.read_text("utf-8") + "\n# added_by_grok\n", "utf-8")
answer = {"text": "I added the line." if mode != "nothing" else "Nothing needed changing.", "stopReason": "cancelled" if mode == "refused" else "end_turn",
          "sessionId": "01a1d9b0-06ba-7d80-9130-690427176efe", "cwd": str(cwd), "num_turns": 2, "total_cost_usd": 0.05,
          "usage": {"input_tokens": 2100, "cache_read_input_tokens": 160, "output_tokens": 29, "total_tokens": 2289},
          "modelUsage": {"grok-4.7-build": {"inputTokens": 2100, "outputTokens": 29}}}
print(json.dumps(answer, indent=2))
if mode == "refused":
    print("permission required: Write `C:\\somewhere\\else.txt` was not run, as a headless run cannot ask for approval", file=sys.stderr)
