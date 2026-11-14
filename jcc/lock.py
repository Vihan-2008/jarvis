"""Single-instance lock so only one Inbox watcher runs (CLI `watch` or the GUI), never two."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: IO[bytes] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fh = open(self.path, "a+b")
        except OSError:
            # Windows refuses to open a file for a moment after another holder deleted it (a lock that was just
            # discarded, while something such as a virus scanner still looks at it): that is "taken", so the caller waits.
            return False
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()).encode())
        fh.flush()
        self._fh = fh
        return True

    def discard(self) -> None:
        """Release, and remove the file as well. For locks named after one chat or one message, which are not needed again."""
        self.release()
        try:
            self.path.unlink()
        except OSError:
            pass   # someone else is using it right now, or it is already gone

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._fh.close()
        self._fh = None

    def __enter__(self) -> InstanceLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def watcher_lock(state_dir: Path) -> InstanceLock:
    return InstanceLock(state_dir / "watcher.lock")
