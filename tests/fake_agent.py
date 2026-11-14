"""Stand-in coding agent for tests. Behaviour comes from FAKEAGENT_MODE_<NAME>:
edit | fail_tests | risk | limit | crash | approval | noop
"""
import os
import sys
from pathlib import Path

name = sys.argv[sys.argv.index("--as") + 1] if "--as" in sys.argv else "agent"
mode = os.environ.get(f"FAKEAGENT_MODE_{name.upper()}", "edit")
cwd = Path.cwd()
init = cwd / "src" / "pkg" / "__init__.py"

if mode == "limit":
    print("Error: You've hit your usage limit. Try again in 5 hours.")
    sys.exit(1)
if mode == "crash":
    print("fatal: not signed in")
    sys.exit(2)
if mode == "edit":
    init.write_text(init.read_text() + "\n\ndef added_by_agent():\n    return 42\n")
elif mode == "fail_tests":
    init.write_text("VALUE = 2\n")
elif mode == "risk":
    p = cwd / "config" / "risk_limits.yaml"
    p.parent.mkdir(exist_ok=True)
    p.write_text("max_drawdown_pct: 0.9\n")
elif mode == "approval":
    (cwd / "NEEDS_APPROVAL.md").write_text("I would need the server password for this.")
    init.write_text(init.read_text() + "\n# partial work\n")
elif mode == "plain":
    (cwd / "RESULT.md").write_text("plain job result")
print(f"{name} finished in mode {mode}")
