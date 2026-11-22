# Reel Explainer Bot

**Share an Instagram reel, YouTube video or Facebook video to Telegram. Get back exactly what you wanted from it: the summary, the tools it mentioned, the steps, a fact check, or how to make one like it with AI.**

A self-hosted Telegram bot. Gemini watches the whole video and listens to the audio, so it catches what's on screen and what's said, not just the caption. It runs free on Gemini's free tier and a free server.

[![CI](https://github.com/theayushgupta08/reel-explainer-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/theayushgupta08/reel-explainer-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

## Why

You save a reel because it mentions a tool, a recipe, a workflow or a claim. A week later you can't remember what it said, and rewatching it three times to catch a URL is painful. This bot turns a reel into text you can read in ten seconds and search later.

## Supported links

| Site | Links | How |
|---|---|---|
| Instagram | reels, posts, IGTV | Downloaded with yt-dlp, then uploaded to Gemini |
| YouTube | videos, Shorts, `youtu.be` links, live replays | Gemini watches the public URL itself; nothing is downloaded |
| Facebook | reels, videos, `fb.watch` and share links | Downloaded with yt-dlp, then uploaded to Gemini |

Videos longer than `MAX_VIDEO_MIN` (default 20 minutes) are refused so one long video can't use up your free tier. Admins can switch sites off with `/set ENABLED_PLATFORMS instagram,youtube`. YouTube only works for public and unlisted videos, not private or age-restricted ones.

## What you can ask for

Send a link and tick any mix of these, then tap **Explain**:

| | |
|---|---|
| 📝 **Summary**: the point in 2-3 sentences | 💡 **Key takeaways**: 3-7 action items |
| 🗣 **What's said**: speech, with exact numbers and names | 📜 **Full transcript** with timestamps, translated if needed |
| 👀 **What's shown**: on-screen text, slides, code | 🔗 **Tools & links**: every app, site or person, with free/paid notes |
| 🪜 **Steps**: the how-to, numbered | ✅ **Fact check**: misleading or outdated claims flagged |
| 🎬 **Make one with AI**: free and paid workflows to recreate the format | 📈 **Why it works**: hook, pacing, editing, what to copy |
| 🎵 **Music & audio**: the track, voice and effects | ✍️ **Content ideas**: 5 original reel ideas inspired by it |

- The bot starts downloading as soon as you send the link, so the answer is quick once you've picked.
- All the sections you tick are answered in **one** Gemini request.
- Afterwards, "Want more from this reel?" buttons fetch any other section without downloading again.
- Your last selection is remembered for the next reel.

## Features

- **Watches the actual video**: picture and audio, not just the caption.
- **Private by default**: only Telegram user IDs you allow can use it.
- **Run it entirely from Telegram**: change models, limits and the prompt, manage users, replace Instagram cookies, read logs, pause, restart, or pull the latest code with `/update`.
- **Built for free tiers**: retries and falls back to a lighter Gemini model when the main one is busy, and limits parallel jobs so a 1 GB VM is enough.
- **Leaves nothing behind**: videos are deleted from the server right after upload and from Gemini when the follow-up window ends.
- **Production-ready deploy**: hardened systemd unit, Docker image, tests and CI.

## Quick start

You need Python 3.11+ and ffmpeg (or Docker), plus:

1. **A Telegram bot token**: message [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
2. **A Gemini API key**: free from [Google AI Studio](https://aistudio.google.com/apikey).
3. **Your Telegram user ID**: start the bot once and send `/start`; it tells you.

```bash
git clone https://github.com/theayushgupta08/reel-explainer-bot.git
cd reel-explainer-bot
cp .env.example .env        # fill in TELEGRAM_BOT_TOKEN and GEMINI_API_KEY
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

Send your bot `/start`, put the ID it replies with into `ALLOWED_USER_IDS` in `.env`, and restart. Then share a reel to the bot: in Instagram tap **Share → Telegram → your bot**, or paste the link.

### Docker

```bash
cp .env.example .env        # fill it in
mkdir data                  # put cookies.txt here (see below)
sudo chown -R 1000:1000 data   # Linux only
docker compose up -d --build
```

### Cookies for Instagram and Facebook (usually needed)

Instagram, and often Facebook, block logged-out downloads, so give the bot a session. YouTube doesn't need one:

1. Log in to Instagram and/or Facebook in your browser with **spare accounts**. Sites can flag accounts used for downloading.
2. Export the cookies as `cookies.txt` with a "Get cookies.txt LOCALLY"-style extension.
3. Send the file to your bot in Telegram as an admin. Each site's cookies replace only that site's old ones, so you can send Instagram and Facebook separately. Your message is deleted after saving. Or place the file next to `bot.py`.

`cookies.txt` is a login secret. Never commit or share it.

## Control it from Telegram

Admins are the users in `ADMIN_USER_IDS`, or every allowed user if that is empty. They get a command menu; `/help` lists everything:

| Command | What it does |
|---|---|
| `/status`, `/logs [N]` | Health, version, memory, usage, recent log lines |
| `/config`, `/set KEY VALUE`, `/reset KEY` | Model, fallbacks, timeouts, limits, log level, default sections. Saved and kept across restarts |
| `/prompt`, `/setprompt`, `/resetprompt` | View or replace the instructions sent to Gemini |
| `/users`, `/allow ID`, `/deny ID`, `/admin ID`, `/unadmin ID` | Manage access |
| `/pause`, `/resume` | Stop or start accepting reels from non-admins |
| `/cookies` | Cookie status. Send a `cookies.txt` file to replace it |
| `/update`, `/restart` | Pull the latest code and restart; restart also updates yt-dlp |

`/set GEMINI_API_KEY …` deletes your message after saving. The Telegram token can only be changed in `.env`.

## Configuration

Everything in [`.env.example`](.env.example) can also be changed at runtime with `/set`, except the Telegram token.

| Setting | Default | Notes |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash` | Main model |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash-lite` | Tried when the main one is overloaded or rate-limited |
| `ALLOWED_USER_IDS` / `ADMIN_USER_IDS` | empty | Comma-separated Telegram user IDs |
| `DEFAULT_SECTIONS` | `summary,takeaways,tools,steps,factcheck` | Pre-ticked for a user's first reel |
| `MAX_CONCURRENT_JOBS` | `2` | Reels processed at once |
| `ENABLED_PLATFORMS` | `instagram,youtube,facebook` | Sites whose links are accepted |
| `MAX_VIDEO_MIN` | `20` | Longer videos are refused |
| `MAX_VIDEO_MB` | `200` | Larger downloads are refused |
| `JOB_TTL_MIN` | `30` | How long follow-up buttons keep working |
| `DATA_DIR` | project folder | Where `settings.json` and `prefs.json` are written |

## Deploy free on Oracle Cloud

An Always Free Ubuntu VM is enough; even the 1 GB E2.1.Micro works. No inbound ports are needed, because the bot polls Telegram.

```bash
sudo useradd --system --home /opt/reel-bot --shell /usr/sbin/nologin reelbot
sudo git clone https://github.com/theayushgupta08/reel-explainer-bot.git /opt/reel-bot
# copy your .env (and cookies.txt) into /opt/reel-bot/
sudo bash /opt/reel-bot/deploy/setup.sh
```

`setup.sh` installs Python and ffmpeg, adds 2 GB of swap, and installs a locked-down systemd service that restarts on failure. Logs: `/logs` in Telegram or `journalctl -u reel-bot -f`. To ship new code, push to your fork and send `/update`.

Only one copy of a bot token can run at a time. A second copy causes 409 Conflict errors.

### Running on Windows

The [`windows/`](windows) folder has `run.bat` (run in a window), `start-hidden.vbs` (run in the background, for example from the Startup folder) and `stop-bot.bat`.

## How it works

```
Telegram link ─▶ yt-dlp downloads the reel ─▶ upload to Gemini Files API
                                              │
user ticks sections ──────────────────────────┴─▶ one generate_content call ─▶ reply
                                                         │
                         "more" buttons reuse the upload ┘   deleted after JOB_TTL_MIN
```

## Good to know

- **Instagram's and Facebook's terms** don't allow automated downloading. This project is for personal, low-volume use of public content. You're responsible for how you use it.
- **Free-tier privacy:** on Gemini's free tier, Google may use inputs to improve its models. Only send public content.
- **Free-tier limits** are per model and change over time. See yours in AI Studio. Each Explain tap uses one request.
- AI answers can be wrong. Treat fact checks and tool prices as a starting point.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a new checklist section is a single entry in [`sections.py`](sections.py). Security issues: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
