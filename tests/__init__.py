"""The tests. They never read one PC's own settings (config/local.toml)."""
import os

os.environ.setdefault("JCC_NO_LOCAL_CONFIG", "1")
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
