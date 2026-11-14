# Security

JARVIS acts on your computer and in your accounts, so a hole in it matters. Reports are welcome.

## Reporting a problem

Please do not open a public issue for something that could be used against people who run the app.
Use GitHub's private reporting instead: on the repository page, **Security**, then **Report a vulnerability**.
Say what you did, what happened, and what you expected. A small way to reproduce it helps most.

You will get an answer. Fixes are released as a new version, with the reporter credited if they wish.

## What counts

- Anything that lets a website, another program on the PC, a web page the assistant reads, an e-mail, a note or a
  project's files make JARVIS do something its owner did not ask for or approve.
- Anything that reads, sends or logs a key, a token or a private note.
- A coding job that can touch the real project folder, a protected folder, or merge without its checks.
- An approval that can be replayed, or used for something other than what was shown.

## What the app is built to guarantee

- It listens on `127.0.0.1` only and takes its port exclusively. Every request needs the token its own window was
  given; requests from another origin or host name are refused.
- Keys are kept in the system key store or in environment variables, and are removed from the environment of every
  coding job and helper. Text is redacted before it is written to notes, logs or chats.
- Every action of the assistant goes through one set of rules (`jcc/policy.py`). An approval is bound to one
  action with its exact details, in one session, once.
- Content from outside (web pages, mail, documents, tool results) is marked as information. Reading it raises how
  much the assistant must ask before it acts.
- A page made by a model is shown in a sealed frame that cannot reach the app, the network (unless you allow it
  for that page) or your files.

## What it does not protect against

- A program already running as your own user account. It can read what you can read.
- The tests of a project you ask a coding agent to work on: they are run, as your user, the way you would run them.
- The command-line tools and services you connect. They have their own security.
