"""The tests. They never read one PC's own settings (config/local.toml)."""
import os

os.environ.setdefault("JCC_NO_LOCAL_CONFIG", "1")
os.environ.setdefault("JCC_NO_DUCKING", "1")      # never turn the PC's real sound down

# On GitHub's machines a run that hangs is cut off with nothing said. There, every thread's place is written out after
# twenty minutes (the whole suite takes about six), and the run stops, so a hang says where it is.
if os.environ.get("GITHUB_ACTIONS") == "true":
    import faulthandler
    import sys
    faulthandler.dump_traceback_later(1200, exit=True, file=sys.stderr)
"""Every test runs away from the real app: nothing here may read or write JARVIS's own folders on this PC."""
import atexit
import os
import shutil
import tempfile

# The assistant's tools look in JARVIS's state folder for "stop was pressed" (and keep a few small files there). A test
# that makes those tools without saying where would look in the real app's folder, and fail whenever its owner had
# pressed stop there. Tests that have a folder of their own (tests/helpers.py) name it themselves.
if "JCC_VOICE_STATE" not in os.environ:
    _folder = tempfile.mkdtemp(prefix="jcc-test-voice-")
    os.environ["JCC_VOICE_STATE"] = _folder
    atexit.register(shutil.rmtree, _folder, ignore_errors=True)


def _agents_present() -> None:
    """Tests that start a job stand in for the coding agent itself, so they must not depend on whether Claude Code or
    Codex happens to be installed on the machine running them. Where one is missing, it still counts as installed."""
    from jcc import agents
    real = agents.available

    def available(agent):
        return real(agent) or bool(agent.enabled and str(agent.command[0]) in ("claude", "codex"))

    agents.available = available


_agents_present()


def _no_real_mute() -> None:
    """Whether Windows has the real microphone muted differs from one machine to the next: tests are told it is not known.
    Tests of that code stand in for it themselves."""
    from jcc import sound
    sound.real_mic_muted = sound.mic_muted
    sound.mic_muted = lambda cfg: None


_no_real_mute()


def _no_real_mac() -> None:
    """On a Mac, JARVIS can look at the real windows, press real keys and move the real pointer (jcc/macax.py). No test may:
    asked for the real Mac, a test is told there is none. Tests of that code bring a stand-in of their own."""
    from jcc import macax

    def mac():
        raise OSError("tests never touch the real Mac")

    macax.mac = mac


_no_real_mac()
