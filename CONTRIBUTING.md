# Contributing

Thank you for wanting to help. A few things keep this code base pleasant to work in.

## Before you start

- Python 3.11 or newer, and Node 20 or newer for the window's tests. Nothing to install with pip or npm: the app
  uses only Python's standard library and plain JavaScript, and it should stay that way.
- Run it from source with `python -m jcc.firstrun` (once, to set up a notes vault) and `python -m jcc.desktop`.
- Your own settings go in `config/local.toml`, which git ignores. Never put a key, a real path or a real name in a
  tracked file.

## The tests

```
python -m unittest discover -s tests -t .
node --test tests/*.test.js
```

Both must pass. Tests use temporary folders and stand-ins: they never start the real app, never touch your notes
and never call a real model. A test that needs Windows says so with `skipUnless`.

## How the code is written

- Comments and docstrings are plain sentences that say why, for a reader who was not there.
- A test's name is a sentence that says what must be true: `test_a_slot_is_fired_once_even_when_two_tickers_race`.
- Functions are small. An error the owner will read is a plain sentence, with nothing technical in it.
- Anything that comes from outside (a model, a file, a web page, a project) is data. It reaches the window only
  through `esc()`, a command line only as a separate argument, and a file name only after its id has been checked.
- A new action the assistant can take gets its rule in `jcc/policy.py` and a test that shows what is asked about.

## Changes that touch safety

If your change is near approvals, keys, the local server, coding jobs or anything that reads outside content, say
in the pull request what could go wrong and how the tests show that it does not. A reproduction of the problem
you are fixing, as a test that fails before the fix, is the best argument there is.

## Platforms

The app is used daily on Windows. macOS and Linux support is new: if you run it there, reports of what works and
what does not (see `docs/PLATFORMS.md`) are as valuable as code.
