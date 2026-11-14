"""First run: choose the notes vault, set it up as JARVIS's second brain, and remember where it is.

The installers run this once (`python -m jcc.firstrun`), and a person who runs JARVIS from source can run it too:

    python -m jcc.firstrun [--vault PATH] [--app-dir PATH] [--yes] [--no-open]

What it does, in order:

1. Chooses the vault: the --vault folder, else the one already named in config/local.toml, else
   "Documents/JARVIS Vault" in the person's home folder. The folder is created if it is missing.
2. Puts in it the folders and starter notes the app expects (the same ones `python -m jcc setup-vault` and the app's
   own start make), plus "Start here.md", which says in plain words what each folder is for.
3. Gives the folder a minimal ".obsidian" settings folder when it has none, so Obsidian opens it as a vault without
   asking questions.
4. Writes `[paths] vault = '...'` into config/local.toml, changing only that one value.
5. Prints the vault's path and, unless --no-open, opens the folder in the system's file manager.

The rules it keeps, because the vault is the person's own notes and local.toml is their own settings:

- An existing folder is never emptied and an existing note is never overwritten. (The app's own generated notes,
  such as System/Router Rules.md, are the one exception, exactly as when the app itself starts.)
- Obsidian's own settings are never edited: an existing ".obsidian" folder, and its plugins, are left alone.
- local.toml is changed by hand, one line, and the result is read back with tomllib before it is saved. A file that
  is not valid TOML is left as it is. A path that cannot be written safely as a TOML literal string (one holding a
  single quote, a line break or another control character) is refused, before anything is created.
- Running it again changes nothing.

Everything is a function that takes its folders as arguments, so the tests run it on temporary folders only.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from jcc.config import ROOT

DEFAULT_VAULT = Path("~") / "Documents" / "JARVIS Vault"

# A table header, [name] or [[name]]. The text written is always read back with tomllib, so a line this takes wrongly
# for a header (it would have to look exactly like one) cannot produce a broken or wrong file.
_SECTION = re.compile(r"^\s*(\[\[?)\s*([A-Za-z0-9_.\-\"' ]+?)\s*\]\]?\s*(#.*)?$")
_VAULT_KEY = re.compile(r"^\s*vault\s*=")

START_HERE = """# Start here

This folder is your **second brain**: a set of plain Markdown notes that you own, that Obsidian shows and edits, and
that JARVIS reads and writes as its memory. Nothing here is locked into JARVIS. If you stop using it, the notes stay
yours and stay readable in any text editor.

## How JARVIS uses this vault

- Every conversation with JARVIS is saved as a note, so you can read it, search it and link to it.
- When you ask something, JARVIS looks for the notes that matter to the question and uses them as background.
- When you say "remember that ...", the fact goes into a note you can read, change or delete.
- Anything in the **Private** folder is never sent to any AI model. JARVIS can still find it on this computer.
- Your keys and passwords are never kept here: they live in the system's own key store.

## What each folder is for

| Folder or note | What it holds |
|---|---|
| **Inbox.md** | Requests you type as `- [ ] ...`; JARVIS picks them up, ticks them and links the answer. |
| **Dashboard.md** | One page with what needs your approval, what is running and what happened today. |
| **Priorities.md**, **Tasks.md** | Your own lists. JARVIS reads them when you ask "what are my priorities" or "what's on today". |
| **Conversations** | Your chats with JARVIS, one note each. |
| **Projects** | One folder per project, with a Memory note of requirements and decisions JARVIS should remember. |
| **Jobs** | One note per larger piece of work JARVIS did for you: what it did, where, and how it went. |
| **Reports**, **Research** | Results and research write-ups from those jobs. |
| **Requests** | A receipt for every request, filed by year and month. |
| **System** | JARVIS's own notes: guides, its memory of things you asked it to remember, rules and usage. |
| **Private** | Notes that never leave this computer. |

You can add your own folders and notes anywhere. JARVIS never deletes or overwrites a note you wrote.

## Next steps

1. Open JARVIS from the Desktop, the Start menu or the Applications folder.
2. Open this folder in Obsidian ("Open folder as vault") if you want to browse and edit your notes there.
3. Read [[System/JARVIS Guide]] for what JARVIS can do.
"""


class FirstRunError(ValueError):
    """A problem the person has to fix (a bad path, a broken settings file). Its text is shown to them as it is."""


# ----------------------------------------------------------------------------------------------- choosing the vault
def _absolute(text: str | os.PathLike) -> Path:
    """A path as typed or as written in the settings, with ~ and variables filled in, made absolute."""
    return Path(os.path.expandvars(os.path.expanduser(str(text)))).absolute()


def configured_vault(app_dir: Path) -> str | None:
    """The vault already named in config/local.toml, as written there, or None. A broken file is reported, not guessed
    at, because the next step would be to change it."""
    local = Path(app_dir) / "config" / "local.toml"
    if not local.is_file():
        return None
    try:
        data = tomllib.loads(local.read_text("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as problem:
        raise FirstRunError(f"{local} is not a valid settings file ({problem}). Fix or remove it, then run this again.")
    value = (data.get("paths") or {}).get("vault") if isinstance(data.get("paths"), dict) else None
    return value if isinstance(value, str) and value.strip() else None


def choose_vault(app_dir: Path, given: str | os.PathLike | None = None) -> Path:
    """The --vault folder, else the one in config/local.toml, else ~/Documents/JARVIS Vault."""
    if given:
        return _absolute(given)
    configured = configured_vault(app_dir)
    return _absolute(configured if configured else DEFAULT_VAULT)


def toml_literal(path: Path) -> str:
    """The path as a TOML literal string. Literal strings take backslashes as they are, which suits Windows paths, but
    they cannot hold a single quote or a line break at all, so such a path is refused rather than escaped."""
    text = str(path)
    if "'" in text:
        raise FirstRunError(f"The folder {text!r} has a single quote (') in its name. Please choose a folder without one.")
    if any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F for c in text):
        raise FirstRunError("The folder's name has a line break or another control character in it. Please choose another folder.")
    return "'" + text + "'"


# ------------------------------------------------------------------------------------------------ config/local.toml
def with_vault_line(text: str, literal: str) -> str:
    """The settings text with `vault = <literal>` under [paths]: the existing line replaced, or a new line added right
    under the [paths] header, or a new [paths] section added at the end. Every other line is kept as it was."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    entry = f"vault = {literal}"
    section, header_at = None, None
    for index, line in enumerate(lines):
        match = _SECTION.match(line.rstrip("\r\n"))
        if match:
            section = match.group(2).replace(" ", "") if match.group(1) == "[" else None
            if section == "paths":
                header_at = index
            continue
        if section == "paths" and _VAULT_KEY.match(line):
            ending = line[len(line.rstrip("\r\n")):] or newline
            lines[index] = entry + ending
            return "".join(lines)
    if header_at is not None:
        lines.insert(header_at + 1, entry + newline)
        if not lines[header_at].endswith(("\n", "\r")):
            lines[header_at] += newline
        return "".join(lines)
    if text and not text.endswith(("\n", "\r")):
        text += newline
    gap = newline if text.strip() else ""
    return f"{text}{gap}[paths]{newline}{entry}{newline}"


def remember_vault(app_dir: Path, vault: Path) -> bool:
    """Write the vault into config/local.toml. Returns False when the file already names this same folder."""
    local = Path(app_dir) / "config" / "local.toml"
    literal = toml_literal(vault)
    configured = configured_vault(app_dir)
    if configured and _absolute(configured) == vault:
        return False
    old = local.read_bytes().decode("utf-8") if local.is_file() else ""
    new = with_vault_line(old, literal)
    try:
        written = tomllib.loads(new)
    except tomllib.TOMLDecodeError as problem:
        raise FirstRunError(f"Could not add the vault to {local} without breaking it ({problem}). "
                            f"Add this line under [paths] yourself: vault = {literal}")
    if (written.get("paths") or {}).get("vault") != str(vault):
        raise FirstRunError(f"Could not add the vault to {local} safely. Add this line under [paths] yourself: vault = {literal}")
    local.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=local.parent, prefix=".local-", suffix=".toml")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(new.encode("utf-8"))
        os.replace(temporary, local)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


# ------------------------------------------------------------------------------------------------------ the vault
def _create_once(path: Path, text: str) -> bool:
    """Write a new file; leave an existing one exactly as it is. Opening with "x" makes that true even if two runs race."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except FileExistsError:
        return False
    return True


def make_obsidian_vault(vault: Path) -> bool:
    """A minimal .obsidian folder, so Obsidian opens the folder as a vault without asking. An existing one is the
    person's own Obsidian settings and is never touched."""
    settings = vault / ".obsidian"
    if settings.exists():
        return False
    return _create_once(settings / "app.json", "{}\n")


def _config_for(vault: Path, state_dir: Path | None):
    """The app's settings with this vault (and, for tests, this data folder) in place of the configured ones."""
    from jcc import config
    overrides = {"paths": {"vault": str(vault), **({"state_dir": str(state_dir)} if state_dir else {})}}
    cfg = config.load(overrides)
    return dataclasses.replace(cfg, vault=vault, state_dir=Path(state_dir) if state_dir else cfg.state_dir)


def build_brain(vault: Path, state_dir: Path | None = None) -> list[str]:
    """The folders and starter notes the app expects, made by the app's own code so they never drift apart. Returns the
    notes that were created."""
    from jcc.initialize import ensure_notes
    from jcc.setup_vault import setup
    before = {p for p in vault.rglob("*.md")} if vault.exists() else set()
    cfg = _config_for(vault, state_dir)
    setup(cfg)
    ensure_notes(cfg)
    (vault / "Projects").mkdir(exist_ok=True)
    (vault / "Notes").mkdir(exist_ok=True)
    _create_once(vault / "Start here.md", START_HERE)
    return sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md") if p not in before)


def open_folder(path: Path) -> None:
    """Show the folder in the system's file manager. Failing to do so is not a reason to fail the setup."""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def reveal(path: Path) -> None:
    """Show a file in the system's file manager, selected in its folder (a folder is simply opened)."""
    path = Path(path)
    if path.is_dir():
        return open_folder(path)
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            open_folder(path.parent)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------- run
def run(app_dir: Path, vault: str | os.PathLike | None = None, *, state_dir: Path | None = None,
        open_it: bool = False) -> list[str]:
    """Do the whole first run and return what was done, as sentences for a person to read."""
    app_dir = Path(app_dir).absolute()
    configured_vault(app_dir)                    # a broken local.toml stops the run before anything is created
    chosen = choose_vault(app_dir, vault)
    toml_literal(chosen)                         # and so does a path that cannot be written into it safely
    if chosen.exists() and not chosen.is_dir():
        raise FirstRunError(f"{chosen} is a file, not a folder. Please choose a folder for your notes.")
    said = []
    if chosen.is_dir():
        said.append(f"Your notes vault is the existing folder {chosen}. Nothing in it was removed or overwritten.")
    else:
        chosen.mkdir(parents=True)
        said.append(f"Created your notes vault at {chosen}.")
    created = build_brain(chosen, state_dir)
    if created:
        said.append(f"Added {len(created)} starter notes and the folders JARVIS uses; read \"Start here.md\" first.")
    else:
        said.append("The vault already had every starter note, so none were added.")
    if make_obsidian_vault(chosen):
        said.append("Marked the folder as an Obsidian vault, so Obsidian can open it straight away.")
    if remember_vault(app_dir, chosen):
        said.append(f"Saved the vault's place in {app_dir / 'config' / 'local.toml'}.")
    else:
        said.append(f"{app_dir / 'config' / 'local.toml'} already pointed at this vault, so it was not changed.")
    said.append(f"To use it in Obsidian, choose \"Open folder as vault\" and pick: {chosen}")
    if open_it:
        open_folder(chosen)
        said.append("Opened the vault folder for you.")
    return said


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m jcc.firstrun", description="Set up the JARVIS notes vault.")
    parser.add_argument("--vault", help="the folder for your notes (created if missing)")
    parser.add_argument("--app-dir", default=str(ROOT), help="the JARVIS folder whose config/local.toml is written")
    parser.add_argument("--yes", action="store_true", help="ask no questions; take the defaults")
    parser.add_argument("--no-open", action="store_true", help="do not open the vault folder afterwards")
    args = parser.parse_args(argv)
    vault = args.vault
    try:
        if not vault and not args.yes and sys.stdin and sys.stdin.isatty():
            offered = choose_vault(Path(args.app_dir))
            answer = input(f"Where should your notes be kept? Press Enter for {offered}\n> ").strip().strip('"')
            vault = answer or str(offered)
        for sentence in run(Path(args.app_dir), vault, open_it=not args.no_open):
            print(sentence)
    except FirstRunError as problem:
        print(f"JARVIS setup stopped: {problem}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
