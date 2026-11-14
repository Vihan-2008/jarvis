import os as _os

_os.environ.setdefault("JCC_NO_LOCAL_CONFIG", "1")      # tests never read one PC's own settings (config/local.toml)
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from jcc import config
from jcc.engine import Engine

FAKE_GEMINI = "AIzaSyFAKEgeminiKEY_1234567890abcdefgh"
FAKE_GROQ = "gsk_FAKEgroqKEY1234567890abcdefGHIJ"
FAKE_BOT = "fake-dashboard-pw-9876"


class FakeTransport:
    """Stands in for the HTTP calls to Gemini/Groq. Records every request body."""

    def __init__(self, classify=None, fail=None, answer="Fake answer."):
        self.calls = []
        self.classify = classify or {}
        self.fail = set(fail or [])
        self.answer = answer

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": body})
        family = "groq" if "groq" in url else "gemini"
        if family in self.fail:
            return 429, {"error": {"message": "quota"}}
        system = body["messages"][0]["content"]
        if "You route requests" in system:
            req = json.loads(body["messages"][1]["content"].split("REQUEST:\n", 1)[1])
            tier, conf = self.classify.get(req, (2, 0.9))
            content = json.dumps({"tier": tier, "confidence": conf, "reason": "fake"})
        else:
            content = self.answer
        return 200, {"choices": [{"message": {"content": content}}],
                     "usage": {"total_tokens": 120}}


def as_windows(case):
    """For tests of the assistant's window tools with stand-ins for the windows, keys and controls: they run on every
    system as they would on Windows, since what they test is the logic and not Windows itself. (Off Windows those tools
    are not offered at all: see jcc/voice_tools.py missing.)"""
    from unittest import mock
    from jcc import system
    original = case.setUp

    def setUp(self):
        patch = mock.patch.object(system, "PLATFORM", "win32")
        patch.start()
        self.addCleanup(patch.stop)
        original(self)
    case.setUp = setUp
    return case


class EngineTestCase(unittest.TestCase):
    keys = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-test-"))
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.state = self.tmp / "state"
        self.jobs_root = self.tmp / "jobs"
        self._env = {k: os.environ.get(k) for k in
                     ("JCC_VAULT", "JCC_STATE_DIR", "JCC_JOBS_ROOT", "JCC_GEMINI_API_KEY",
                      "JCC_GROQ_API_KEY", "JCC_BOT_PASSWORD", "JCC_NO_CREDMAN", "JCC_NO_SCREEN", "JCC_PROJECTS_ROOT", "JCC_VOICE_STATE")}
        os.environ["JCC_NO_CREDMAN"] = "1"
        os.environ["JCC_NO_SCREEN"] = "1"          # the windows open on the real PC are not part of any test
        os.environ["JCC_VAULT"] = str(self.vault)
        os.environ["JCC_STATE_DIR"] = str(self.state)
        os.environ["JCC_JOBS_ROOT"] = str(self.jobs_root)
        os.environ["JCC_PROJECTS_ROOT"] = str(self.tmp / "projects")      # a project a test creates is a real folder: it goes with the test
        os.environ["JCC_VOICE_STATE"] = str(self.state)                   # the assistant's tools look here for "stop was pressed": never in the real app's folder
        if self.keys:
            os.environ["JCC_GEMINI_API_KEY"] = FAKE_GEMINI
            os.environ["JCC_GROQ_API_KEY"] = FAKE_GROQ
            os.environ["JCC_BOT_PASSWORD"] = FAKE_BOT
        else:
            for k in ("JCC_GEMINI_API_KEY", "JCC_GROQ_API_KEY", "JCC_BOT_PASSWORD"):
                os.environ.pop(k, None)
        self.spawned = []
        self.transport = FakeTransport()

    def make_engine(self, overrides=None, **kw):
        cfg = config.load(overrides)
        kw.setdefault("transport", self.transport)
        kw.setdefault("spawner", lambda argv, cwd, env: self.spawned.append((argv, cwd, env)) or 1)
        self.engine = Engine(cfg, **kw)
        return self.engine

    def tearDown(self):
        if getattr(self, "engine", None):
            self.engine.close()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")

    def all_written_text(self):
        out = []
        for root in (self.vault, self.state, self.jobs_root):
            for p in root.rglob("*") if root.exists() else []:
                if p.is_file():
                    out.append((p, p.read_bytes().decode("utf-8", errors="ignore")))
        return out
