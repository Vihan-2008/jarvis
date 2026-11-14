"""Playing music where the user plays it: in the Spotify app when it is there, otherwise on YouTube.

"Play X" means X is playing when JARVIS answers, not that a page of search results is on the screen.

Spotify has no way in for another program without an account key, so its own keyboard is used: ctrl+k opens its quick
search, the words are typed, and Enter plays the first result. Spotify shows the song that is playing in its window
title ("Artist - Song"), which is how JARVIS knows that it really started.
"""
from __future__ import annotations

import re
import time

IDLE_TITLE = re.compile(r"^\s*spotify(\s+(premium|free))?\s*$", re.I)
# Words that name no song at all: "play it", "play something". The assistant works out what is meant; nothing is searched for.
VAGUE = re.compile(r"^(?:it|that|this|them|those|these|one|that one|this one|the same|the same (?:song|one|thing)|something|anything|"
                   r"some music|music|a song|songs?|some songs?|the song|the video|the first one)$|\b(?:it|that|this|them)$", re.I)


def spotify_window(windows) -> int:
    """The Spotify app's window, or 0. It is found by its program, because its title is the song while one is playing."""
    for row in windows.all():
        try:
            if windows.app(row["handle"]).lower() == "spotify":
                return int(row["handle"])
        except (AttributeError, OSError, ValueError):
            return 0
    return 0


def _playing(title: str) -> bool:
    return bool(title.strip()) and not IDLE_TITLE.match(title)


def play_in_spotify(query: str, windows, desktop, handle: int = 0, launch=None, press_play=None, pause=time.sleep, patience: float = 12.0) -> str:
    """Start `query` playing in the Spotify app and report what Spotify then shows as playing.

    windows: all(), app(handle), title(handle), focus(handle), foreground().  desktop: perform({"action": ...}).
    launch(): open Spotify when it is not running.  press_play(handle): press Spotify's own Play button (True if it did)."""
    query = " ".join(str(query).split())[:120]
    if not query:
        return "Nothing was named to play."
    handle = handle or spotify_window(windows)
    if not handle and launch:
        launch()
        waited = 0.0
        while not handle and waited < patience:
            pause(0.5)
            waited += 0.5
            handle = spotify_window(windows)
        if handle:
            pause(2.0)          # let it finish starting before its search is used
    if not handle:
        return "Spotify is not open on this PC and could not be started. Say so, or play it on YouTube instead (where: youtube)."
    before = windows.title(handle)
    for wait in (0.25, 0.4, 0.6):
        if windows.foreground() == handle:
            break
        windows.focus(handle)
        pause(wait)
    if windows.foreground() != handle:
        return "Spotify could not be brought to the front, so nothing was typed. Try focus_window with Spotify, then play_music again."
    desktop.perform({"action": "key", "keys": "ctrl+k"})
    pause(0.6)
    desktop.perform({"action": "type", "text": query})
    pause(1.8)                  # the results appear while typing
    if windows.foreground() != handle:
        return "Another window came to the front while typing, so Enter was not pressed. Nothing is playing yet."
    desktop.perform({"action": "key", "keys": "enter"})
    title = before
    for _ in range(12):
        pause(0.4)
        title = windows.title(handle)
        if _playing(title) and title != before:
            return f'Now playing in Spotify: "{title[:90]}".'
    if not _playing(title) and press_play:
        # An artist, an album or a playlist opened instead of a song starting: press its Play button.
        try:
            pressed = press_play(handle)
        except Exception:  # noqa: BLE001 - whatever the window does, report what is known
            pressed = False
        if pressed:
            for _ in range(10):
                pause(0.4)
                title = windows.title(handle)
                if _playing(title):
                    return f'Now playing in Spotify: "{title[:90]}".'
    if _playing(title) and title == before and all(word in title.lower() for word in re.findall(r"[a-z0-9']{3,}", query.lower())[:2]):
        return f'Spotify is already playing "{title[:90]}".'
    return (f'"{query}" was typed into Spotify\'s search and Enter was pressed, but Spotify does not show a new song playing'
            + (f' (it still shows "{title[:60]}")' if _playing(title) else "") +
            ". Do not say it is playing. Look with list_controls or see_screen and press the right result or its Play button, or name the exact song and artist.")


def play_on_youtube(query: str, finder=None, opener=None) -> str:
    """Start the first matching video on YouTube in the user's own browser."""
    if finder is None:
        from jcc.webread import find_videos as finder
    if opener is None:
        import webbrowser
        opener = webbrowser.open
    try:
        rows = finder(query, limit=1)
    except ValueError as problem:
        return f"YouTube could not be searched ({problem}). Nothing is playing."
    if not rows:
        return "No video was found for that on YouTube. Nothing is playing. Try other words."
    opener(rows[0]["url"])
    return f'Now playing on YouTube: "{(rows[0].get("title") or query)[:90]}".'


def play(query: str, where: str, windows, desktop, launch=None, press_play=None, has_spotify: bool = False, finder=None, opener=None, pause=time.sleep) -> str:
    """Play `query` in Spotify or on YouTube. With no place named: Spotify if the app is open or installed, otherwise YouTube."""
    place = str(where or "").strip().lower()
    handle = spotify_window(windows)
    if "youtube" in place or "you tube" in place or "video" in place:
        return play_on_youtube(query, finder, opener)
    if "spotify" in place or handle or has_spotify:
        return play_in_spotify(query, windows, desktop, handle, launch, press_play, pause)
    return play_on_youtube(query, finder, opener)
