# Contributing

Thanks for helping out. Bug reports, new reel sections, docs fixes and deploy guides for other hosts are all welcome.

## Set up

```bash
git clone https://github.com/theayushgupta08/reel-explainer-bot.git
cd reel-explainer-bot
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # add a test bot token from @BotFather and a Gemini key
python bot.py
```

Use a separate test bot. Two processes polling the same token fight each other (HTTP 409 Conflict).

## Before you open a pull request

```bash
ruff check .
pytest -q
```

CI runs the same two commands. Please:

- Keep pull requests focused on one change.
- Add or update tests for behaviour changes. The tests fake Telegram, Instagram and Gemini, so they need no network or keys.
- Update the README when you add a setting, command or section.

## Adding a section to the checklist

Sections live in [`sections.py`](sections.py). Add a `Section(key, label, heading, instruction)` to `SECTIONS`. The key must be short (callback data is limited to 64 bytes), and the instruction should tell Gemini exactly what to write. No other code changes are needed.

## Never commit

`.env`, `cookies.txt`, `settings.json`, `prefs.json` or logs. They are in `.gitignore`; please keep it that way.

## Conduct

Be kind and assume good faith. Harassment or personal attacks aren't tolerated; maintainers may remove comments or contributors that cross that line.
