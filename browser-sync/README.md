# JARVIS browser sync — one-time setup

1. In Chrome open `chrome://extensions`, or in Edge open `edge://extensions`.
2. Turn on Developer mode, choose **Load unpacked**, and select this `browser-sync` folder.
3. Open the JARVIS desktop app → Workspace details → **Copy browser pairing code**.
4. Click the extension, paste the code, and choose **Connect to JARVIS**.
5. Refresh a saved ChatGPT or Claude conversation. Check that JARVIS shows the last website capture.

The pairing survives browser and JARVIS restarts. Keep using your existing browser sign-ins.
Provider sign-ins can expire independently. Removing the `browser-sync-key` file invalidates the pairing.

This is a local, unpacked extension, not a store-reviewed extension. Read its files before loading it.
It reads visible conversation text only on chatgpt.com and claude.ai, stores a bounded offline queue,
and sends it only to `127.0.0.1:8765`. It does not access account passwords or cookies.

It captures saved conversations while opened in this browser. It does not crawl your account,
capture chats on another device, download attachments or reconstruct hidden conversation branches.
Website markup changes can interrupt capture. Full account exports provide the historical archive.
