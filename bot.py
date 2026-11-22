"""Reel Explainer Bot.

Send it an Instagram reel link on Telegram; it downloads the reel, has Gemini
watch it (video + audio + caption), and replies with the full context.

All secrets come from environment variables (or a local .env file).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)  # so .env and cookies.txt resolve however the bot is launched
load_dotenv(BASE_DIR / ".env")

# LOG_FILE: path for a rotating log file; set to "" to log to stdout only (systemd/journald).
_log_file = os.getenv("LOG_FILE", "bot.log").strip()
_handlers: list[logging.Handler] = []
if _log_file:
    _handlers.append(
        RotatingFileHandler(BASE_DIR / _log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    )
if sys.stderr is not None:  # pythonw (hidden auto-start) has no console
    _handlers.append(logging.StreamHandler())
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    handlers=_handlers,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("reel-bot")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var {name}. See .env.example.")
    return value


TELEGRAM_BOT_TOKEN = _required("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = _required("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
# Tried in order when the main model is overloaded (503) or rate-limited (429).
GEMINI_FALLBACK_MODELS = [
    m for m in re.split(r"[,\s]+", os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite")) if m
]
INSTAGRAM_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "").strip() or None
# How many reels are processed at once; keeps memory bounded on a small VM.
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "2")))
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "200"))
ALLOWED_USER_IDS = {
    int(x) for x in re.split(r"[,\s]+", os.getenv("ALLOWED_USER_IDS", "")) if x.strip()
}

REEL_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/[\w-]+[^\s]*",
    re.IGNORECASE,
)

PROMPT = """You are watching an Instagram reel. Watch the full video AND listen to the audio.
Explain the reel so the viewer gets its whole context without rewatching it.

Reply in plain text (no markdown symbols like ** or #). Use this structure:

SUMMARY
2-3 sentences on what the reel is about and its main point.

WHAT'S SAID
The key points from the speech/voiceover, in order. Quote exact numbers, names and claims.
If there is no speech, say so and describe the audio (music, sounds).

WHAT'S SHOWN
Important on-screen text, slides, code, products, places or demos that the audio doesn't cover.

TOOLS, LINKS & NAMES
Every app, website, product, book, person or account mentioned or shown. Write "None" if none.

STEPS / HOW-TO
If the reel teaches something, the exact steps. Otherwise skip this section.

FACT CHECK
Flag claims that are misleading, outdated, exaggerated or unverifiable, briefly and honestly.
Write "Nothing notable" if it holds up.

Context from the post itself:
Creator: {uploader}
Caption: {caption}
"""

TELEGRAM_LIMIT = 4000  # Telegram's hard limit is 4096; leave headroom.

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------- download ----------

def download_reel(url: str, workdir: Path) -> tuple[Path, dict]:
    opts = {
        "outtmpl": str(workdir / "reel.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_VIDEO_MB * 1024 * 1024,
        "socket_timeout": 30,
        "retries": 3,
    }
    if INSTAGRAM_COOKIES_FILE:
        opts["cookiefile"] = INSTAGRAM_COOKIES_FILE
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = next(e for e in info["entries"] if e)
    videos = sorted(workdir.glob("reel.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not videos:
        raise RuntimeError("Download finished but no video file was found.")
    return videos[0], info


# ---------- gemini ----------

RETRYABLE_CODES = {429, 500, 503}
# Give up on a single call after 90s so an overloaded model can't hang the bot.
GENERATE_CONFIG = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=90_000))


def _generate_with_fallback(contents):
    """Try the main model (with retries), then each fallback model."""
    last_error: Exception | None = None
    for model in [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=GENERATE_CONFIG
                )
                if model != GEMINI_MODEL:
                    log.info("Answered by fallback model %s", model)
                return response
            except genai_errors.APIError as e:
                if getattr(e, "code", None) not in RETRYABLE_CODES:
                    raise
                last_error = e
                log.warning("%s busy (%s), attempt %d", model, e.code, attempt + 1)
            except Exception as e:  # noqa: BLE001 - only swallow timeouts
                if "timeout" not in type(e).__name__.lower():
                    raise
                last_error = e
                log.warning("%s timed out, attempt %d", model, attempt + 1)
                break  # a hung model rarely recovers quickly; go to the next one
            time.sleep(3 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def explain_video(video: Path, info: dict) -> str:
    uploaded = client.files.upload(file=str(video), config={"mime_type": "video/mp4"})
    try:
        deadline = time.time() + 180
        while uploaded.state and uploaded.state.name == "PROCESSING":
            if time.time() > deadline:
                raise RuntimeError("Gemini took too long to process the video.")
            time.sleep(2)
            uploaded = client.files.get(name=uploaded.name)
        if uploaded.state and uploaded.state.name == "FAILED":
            raise RuntimeError("Gemini could not process this video.")

        prompt = PROMPT.format(
            uploader=info.get("uploader") or info.get("channel") or "unknown",
            caption=(info.get("description") or "(no caption)")[:3000],
        )
        response = _generate_with_fallback([uploaded, prompt])
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty answer (it may have been blocked).")
        return text
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            log.warning("Could not delete uploaded file %s", uploaded.name)


# ---------- telegram ----------

def _split(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def _allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user) and user.id in ALLOWED_USER_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _allowed(update):
        await update.message.reply_text(
            f"This is a private bot. Your Telegram user ID is {user.id}.\n"
            "If you own this bot, add it to ALLOWED_USER_IDS in .env and restart."
        )
        return
    await update.message.reply_text(
        "Send or share an Instagram reel link and I'll explain the whole thing."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text(
            f"Private bot. Your user ID is {update.effective_user.id}."
        )
        return

    urls = REEL_URL_RE.findall(update.message.text or "")
    if not urls:
        await update.message.reply_text("Send me an Instagram reel link (instagram.com/reel/...).")
        return

    for url in dict.fromkeys(urls):  # dedupe, keep order
        await process_reel(update, context, url)


_job_slots: asyncio.Semaphore | None = None


async def process_reel(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    assert _job_slots is not None
    queued = _job_slots.locked()
    status = await update.message.reply_text(
        "Queued, other reels are being processed..." if queued else "Downloading the reel..."
    )
    async with _job_slots:
        if queued:
            await status.edit_text("Downloading the reel...")
        await _process_reel(update, context, url, status)


async def _process_reel(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, status) -> None:
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    workdir = Path(tempfile.mkdtemp(prefix="reel_"))
    try:
        try:
            video, info = await asyncio.to_thread(download_reel, url, workdir)
        except yt_dlp.utils.DownloadError as e:
            log.warning("Download failed for %s: %s", url, e)
            hint = "" if INSTAGRAM_COOKIES_FILE else (
                "\n\nInstagram often needs a logged-in session. Set INSTAGRAM_COOKIES_FILE in .env "
                "(see README)."
            )
            await status.edit_text(f"Couldn't download that reel.{hint}")
            return
        except Exception:  # noqa: BLE001
            log.exception("Unexpected download error for %s", url)
            await status.edit_text("Something went wrong while downloading that reel.")
            return

        await status.edit_text("Watching it with Gemini...")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        try:
            answer = await asyncio.to_thread(explain_video, video, info)
        except genai_errors.APIError as e:
            log.warning("Gemini API error: %s", e)
            code = getattr(e, "code", None)
            if code == 429:
                await status.edit_text("Hit the Gemini free-tier rate limit. Try again in a minute.")
            elif code in (500, 503):
                await status.edit_text("Gemini's free models are overloaded right now. Try again in a few minutes.")
            else:
                await status.edit_text(f"Gemini rejected the request (error {code}).")
            return
        except Exception:  # noqa: BLE001
            log.exception("Gemini failed for %s", url)
            await status.edit_text("Gemini failed to explain this reel. Try again later.")
            return

        await status.delete()
        header = f"{info.get('uploader') or 'Reel'} | {url}\n\n"
        for chunk in _split(header + answer):
            await update.message.reply_text(chunk, disable_web_page_preview=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


_lock_handle = None


def _acquire_single_instance_lock() -> bool:
    """Only one copy may poll Telegram at a time, or both get 409 Conflict errors."""
    global _lock_handle
    _lock_handle = open(BASE_DIR / "bot.lock", "w")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error while handling an update", exc_info=context.error)


async def _post_init(app: Application) -> None:
    global _job_slots
    _job_slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    me = await app.bot.get_me()
    log.info("Logged in as @%s", me.username)


def main() -> None:
    if not _acquire_single_instance_lock():
        log.error("The bot is already running (auto-start or another window). Exiting.")
        sys.exit(1)
    if not ALLOWED_USER_IDS:
        log.warning(
            "ALLOWED_USER_IDS is empty: the bot will refuse everyone. "
            "Message it /start to learn your user ID, then add it to .env."
        )
    log.info("Starting bot with model %s", GEMINI_MODEL)
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(_post_init)
        .build()
    )
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # bootstrap_retries=-1: at boot Wi-Fi may not be up yet, so keep retrying instead of exiting.
    app.run_polling(allowed_updates=["message"], bootstrap_retries=-1, drop_pending_updates=False)


if __name__ == "__main__":
    main()
