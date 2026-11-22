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

## Choosing what you get

When you send a reel link, the bot starts downloading it straight away and shows a checklist: Summary, Key takeaways, What's said, Full transcript, What's shown, Tools & links, Steps, Fact check, Make one with AI (free and paid workflows), Why it works, Music & audio, and Content ideas. Tick any combination and tap **Explain**. Your last choice is remembered for the next reel.

After the answer, a "Want more from this reel?" menu lets you request any other section without re-downloading. It stays available for `JOB_TTL_MIN` minutes (default 30). Admins can change the starting ticks for new users with `/set DEFAULT_SECTIONS summary,tools,steps`.

## Control it from Telegram

Admins (`ADMIN_USER_IDS`, or every allowed user if that is empty) get a command menu. Send `/help` for the full list:

- `/status`, `/logs [N]`: health, version, memory, usage, recent log lines
- `/config`, `/set KEY VALUE`, `/reset KEY`: change the model, fallbacks, timeouts, limits and log level. Changes are saved to `settings.json` and survive restarts. `/set GEMINI_API_KEY ...` deletes your message after saving.
- `/prompt`, `/setprompt`, `/resetprompt`: view or replace the Gemini instructions
- `/users`, `/allow ID`, `/deny ID`, `/admin ID`, `/unadmin ID`: manage access
- `/pause`, `/resume`: stop or start accepting reels from non-admins
- `/cookies`: check the cookies; send a file named `cookies.txt` to replace it (the message is deleted after saving)
- `/update`: `git pull` the latest code from GitHub, install requirements and restart
- `/restart`: restart (also updates yt-dlp)

`TELEGRAM_BOT_TOKEN` can only be changed in `.env` on the server.

## Server deployment (Oracle Cloud Always Free, Ubuntu)

The server runs a git checkout at `/opt/reel-bot`, owned by the `reelbot` service user, which pulls from GitHub with a read-only deploy key stored in `/etc/reel-bot/`.

1. Create an Always Free VM (Ubuntu 24.04). No inbound ports are needed; the bot polls Telegram.
2. Create a deploy key and add it to the repo as read-only (GitHub → Settings → Deploy keys):
   ```bash
   sudo mkdir -p /etc/reel-bot && sudo ssh-keygen -t ed25519 -N "" -f /etc/reel-bot/deploy_key
   sudo cat /etc/reel-bot/deploy_key.pub
   ```
3. Clone and configure:
   ```bash
   sudo useradd --system --home /opt/reel-bot --shell /usr/sbin/nologin reelbot
   ssh-keyscan github.com | sudo tee /etc/reel-bot/known_hosts
   sudo chown -R reelbot:reelbot /etc/reel-bot && sudo chmod 600 /etc/reel-bot/deploy_key
   SSHCMD="ssh -i /etc/reel-bot/deploy_key -o UserKnownHostsFile=/etc/reel-bot/known_hosts"
   sudo GIT_SSH_COMMAND="$SSHCMD" git clone git@github.com:<you>/reel-explainer-bot.git /opt/reel-bot
   sudo git -C /opt/reel-bot config core.sshCommand "$SSHCMD"
   ```
4. Copy `.env` and `cookies.txt` into `/opt/reel-bot/`, then run `sudo bash /opt/reel-bot/deploy/setup.sh`.
5. Stop any other copy of the bot (for example the Windows one). Two copies polling the same token cause 409 Conflict errors.

- **Logs:** `/logs` in Telegram, or `journalctl -u reel-bot -f`
- **Deploy new code:** push to GitHub, then send `/update`

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q
```
CI runs the same checks on every push.
