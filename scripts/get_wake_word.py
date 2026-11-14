"""Fetch the three small files of the "Hey JARVIS" wake word model into a folder.

    python scripts/get_wake_word.py [FOLDER]

FOLDER defaults to "wake-models" in JARVIS's own state folder, which is where jcc/wakeword.py looks. The model is
openWakeWord's "hey jarvis" (github.com/dscripka/openWakeWord). Its code is Apache 2.0; its makers license the model
files themselves CC BY-NC-SA 4.0, so they are free for non-commercial use. JARVIS does not ship them: each person
fetches them from where their makers publish them.

Each file is checked against a known SHA-256 and is only kept when it matches, so a changed or damaged download is
never used. The model also needs two Python packages: numpy and onnxruntime.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
FILES = {"melspectrogram.onnx": (1087958, "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"),
         "embedding_model.onnx": (1326578, "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"),
         "hey_jarvis_v0.1.onnx": (1271370, "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb")}


def good(path: Path, size: int, digest: str) -> bool:
    try:
        return path.stat().st_size == size and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    except OSError:
        return False


def fetch(folder: Path, get=None, say=print) -> bool:
    """Put the three files into the folder. True when all three are there and are the known ones."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import jcc                                          # noqa: F401 - (on a Mac it gives Python the Mac's own certificates; see jcc.trust_store)
    folder.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        target = folder / name
        if good(target, size, digest):
            say(f"{name}: already there")
            continue
        try:
            if get:
                data = get(SOURCE + name)
            else:
                with urllib.request.urlopen(urllib.request.Request(SOURCE + name, headers={"User-Agent": "jarvis-setup"}), timeout=120) as answer:
                    data = answer.read(size + 1)
        except OSError as problem:
            say(f"{name}: could not be fetched ({problem})")
            return False
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            say(f"{name}: what arrived is not the known file, so it was not kept")
            return False
        partial = target.with_name(name + ".part")
        partial.write_bytes(data)
        partial.replace(target)
        say(f"{name}: fetched and checked")
    return True


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        folder = Path(argv[1]).expanduser()
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from jcc.config import load
        folder = load().state_dir / "wake-models"
    done = fetch(folder)
    print(("The wake word model is in " if done else "The wake word model is not complete in ") + str(folder))
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
