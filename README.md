# Reel Explainer Bot

A private Telegram bot. Share an Instagram reel to it and it replies with the reel's full context: summary, what's said, what's shown on screen, tools and links mentioned, steps, and a fact check. Gemini (free tier) watches the video and listens to the audio directly.

## Setup (Windows, one time)

1. **Telegram bot token.** In Telegram, open @BotFather, send `/newbot`, and copy the token.
2. **Gemini API key.** Go to https://aistudio.google.com/apikey and create a key. No card is needed.
3. **Create `.env`.** Copy `.env.example` to `.env` and paste in both values. Leave `ALLOWED_USER_IDS` empty for now.
4. **Run the bot.** Double-click `run.bat`. The first run creates `.venv` and installs the packages.
5. **Lock the bot to yourself.** Message your bot `/start`. It replies with your user ID. Put that number in `ALLOWED_USER_IDS` in `.env`, close the window, and run `run.bat` again.

## Auto-start with Windows

The shortcut `Reel Explainer Bot` in your Windows Startup folder runs `start-hidden.vbs` each time you log in. It updates `yt-dlp` and then starts the bot in the background with no window.

- **Stop it:** double-click `stop-bot.bat`.
- **Start it again without rebooting:** double-click `start-hidden.vbs`.
- **See what it's doing:** open `bot.log` in this folder.
- **Turn off auto-start:** press Win+R, type `shell:startup`, and delete `Reel Explainer Bot`.
- Only one copy of the bot can run at a time. If the hidden one is running, `run.bat` exits with "already running". To watch the bot live in a window, run `stop-bot.bat` first, then `run.bat`.

## Instagram cookies (usually needed)

Instagram blocks most logged-out downloads. To give the bot a session:

1. Log in to Instagram in your browser, ideally with a **spare account**, because Instagram can flag scraping accounts.
2. Install a "Get cookies.txt LOCALLY" type extension and export the cookies for `instagram.com` as `cookies.txt`.
3. Save it in this folder and set `INSTAGRAM_COOKIES_FILE=cookies.txt` in `.env`.

`cookies.txt` is a login secret. It is already listed in `.gitignore`. Never share it.

## Usage

In the Instagram app, tap **Share → Telegram → your bot**, or paste a link such as `https://www.instagram.com/reel/...`. Messages containing several links are processed one by one.

## Notes

- **Free-tier limits:** Google sets per-minute and per-day request caps. If you hit one, the bot tells you to retry. Your current limits are shown in AI Studio.
- **Privacy:** on the free tier, Google may use uploads to improve its models. Only send public content.
- **Model:** `GEMINI_MODEL` defaults to `gemini-3.5-flash`. When it's overloaded, the bot retries and then falls back to the models in `GEMINI_FALLBACK_MODELS` (default `gemini-3.5-flash-lite`).
- **The bot only runs while this PC is on and you're logged in.** Both launchers update `yt-dlp` on every start, because Instagram changes often break older versions.
- Downloading reels is against Instagram's terms. Keep it personal and low-volume.

## Server deployment (Oracle Cloud Always Free, Ubuntu)

1. Create an Always Free VM (Ubuntu 22.04/24.04; Ampere A1 or E2.1.Micro). No inbound ports are needed; the bot polls Telegram.
2. Stop the Windows copy first (`stop-bot.bat`) and remove the Startup shortcut. Two copies polling the same token cause 409 Conflict errors.
3. On the VM:
   ```bash
   git clone https://github.com/<you>/reel-explainer-bot.git && cd reel-explainer-bot
   ```
4. From your PC, copy the secrets over: `scp .env cookies.txt ubuntu@<vm-ip>:/tmp/`, then on the VM: `sudo mkdir -p /opt/reel-bot && sudo mv /tmp/.env /tmp/cookies.txt /opt/reel-bot/`.
5. `sudo bash deploy/setup.sh` installs Python, ffmpeg, 2 GB swap, a locked-down `reelbot` user and the `reel-bot` systemd service.

- **Logs:** `journalctl -u reel-bot -f`
- **Restart:** `sudo systemctl restart reel-bot` (also updates yt-dlp)
- **Deploy new code:** `sudo bash deploy/update.sh`

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q
```
CI runs the same checks on every push.
