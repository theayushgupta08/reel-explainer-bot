# Security policy

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: **Security → Report a vulnerability** on this repository. You'll get a reply within a few days.

Useful details: what an attacker can do, the steps to reproduce, and the version (`/status` shows the commit).

## What matters most here

- Anything that lets a non-allowed Telegram user use the bot or run admin commands.
- Leaks of secrets: the Telegram token, Gemini API key or Instagram `cookies.txt`.
- Path traversal or code execution through settings, uploaded files or reel URLs.

## Running it safely

- Keep `ALLOWED_USER_IDS` and `ADMIN_USER_IDS` set. With both empty the bot refuses everyone.
- Use a spare Instagram account for `cookies.txt`, never your main one.
- On a server, run it as the unprivileged `reelbot` user with the provided systemd unit, which locks the filesystem down.
