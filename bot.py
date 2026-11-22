"""Reel Explainer Bot.

Send it an Instagram reel link on Telegram; it downloads the reel, has Gemini
watch it (video + audio + caption), and replies with the full context.

Secrets and defaults come from environment variables (or a local .env file).
Admins can change settings, users, cookies and the prompt, and update or
restart the bot, from Telegram. See /help.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import platform
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
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from settings_store import SPECS, Settings

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)  # so .env and cookies.txt resolve however the bot is launched
load_dotenv(BASE_DIR / ".env")

settings = Settings(BASE_DIR / "settings.json")

# ---------- logging ----------


class _MemoryLog(logging.Handler):
    """Keeps the last lines in memory so admins can read them with /logs."""

    def __init__(self, size: int = 400):
        super().__init__()
        self.lines: collections.deque[str] = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


memory_log = _MemoryLog()
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
memory_log.setFormatter(_formatter)

# LOG_FILE: path for a rotating log file; set to "" to log to stdout only (systemd/journald).
_log_file = os.getenv("LOG_FILE", "bot.log").strip()
_handlers: list[logging.Handler] = [memory_log]
if _log_file:
    _handlers.append(
        RotatingFileHandler(BASE_DIR / _log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    )
if sys.stderr is not None:  # pythonw (hidden auto-start) has no console
    _handlers.append(logging.StreamHandler())
for _h in _handlers:
    _h.setFormatter(_formatter)
logging.basicConfig(level=settings.get("LOG_LEVEL"), handlers=_handlers)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("reel-bot")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var {name}. See .env.example.")
    return value


TELEGRAM_BOT_TOKEN = _required_env("TELEGRAM_BOT_TOKEN")
if not settings.get("GEMINI_API_KEY"):
    raise SystemExit("Missing GEMINI_API_KEY. See .env.example.")

REEL_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/[\w-]+[^\s]*",
    re.IGNORECASE,
)
TELEGRAM_LIMIT = 4000  # Telegram's hard limit is 4096; leave headroom.
STARTED_AT = time.time()
RESTART_EXIT_CODE = 3  # any non-zero exit makes systemd (Restart=always) start us again

_client: genai.Client | None = None
_client_key = ""


def gemini() -> genai.Client:
    """Gemini client, rebuilt when the API key is changed from Telegram."""
    global _client, _client_key
    key = settings.get("GEMINI_API_KEY")
    if _client is None or key != _client_key:
        _client, _client_key = genai.Client(api_key=key), key
    return _client


def cookies_file() -> str | None:
    path = settings.get("INSTAGRAM_COOKIES_FILE").strip()
    return path if path and Path(path).exists() else None


# ---------- download ----------


def download_reel(url: str, workdir: Path) -> tuple[Path, dict]:
    opts = {
        "outtmpl": str(workdir / "reel.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": settings.get("MAX_VIDEO_MB") * 1024 * 1024,
        "socket_timeout": 30,
        "retries": 3,
    }
    if cookie_path := cookies_file():
        opts["cookiefile"] = cookie_path
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


def _generate_with_fallback(contents):
    """Try the main model (with retries), then each fallback model."""
    main = settings.get("GEMINI_MODEL")
    config = types.GenerateContentConfig(
        http_options=types.HttpOptions(timeout=settings.get("GEMINI_TIMEOUT_S") * 1000)
    )
    last_error: Exception | None = None
    for model in [main, *settings.get("GEMINI_FALLBACK_MODELS")]:
        for attempt in range(3):
            try:
                response = gemini().models.generate_content(model=model, contents=contents, config=config)
                if model != main:
                    log.info("Answered by fallback model %s", model)
                return response
            except genai_errors.APIError as e:
                if getattr(e, "code", None) not in RETRYABLE_CODES:
                    raise
                last_error = e
                log.warning("%s busy (%s), attempt %d", model, e.code, attempt + 1)
            except Exception as e:
                if "timeout" not in type(e).__name__.lower():
                    raise
                last_error = e
                log.warning("%s timed out, attempt %d", model, attempt + 1)
                break  # a hung model rarely recovers quickly; go to the next one
            time.sleep(3 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def explain_video(video: Path, info: dict) -> str:
    client = gemini()
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

        prompt = settings.get("PROMPT").format(
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
        except Exception:
            log.warning("Could not delete uploaded file %s", uploaded.name)


# ---------- access control ----------


def admin_ids() -> set[int]:
    # With no explicit admins, every allowed user is an admin (a private one-person bot).
    return set(settings.get("ADMIN_USER_IDS")) or set(settings.get("ALLOWED_USER_IDS"))


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user) and user.id in admin_ids()


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user) and (user.id in settings.get("ALLOWED_USER_IDS") or user.id in admin_ids())


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_admin(update):
            log.warning("Non-admin %s tried %s", update.effective_user.id, update.message.text)
            await update.message.reply_text("Admins only.")
            return
        await func(update, context)

    wrapper.__name__ = func.__name__
    return wrapper


# ---------- helpers ----------


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


async def reply_long(update: Update, text: str) -> None:
    for chunk in _split(text):
        await update.message.reply_text(chunk, disable_web_page_preview=True)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


async def _run(*cmd: str, timeout: int = 300) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=BASE_DIR, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 124, f"timed out after {timeout}s"
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def git_version() -> str:
    if not (BASE_DIR / ".git").exists():
        return "not a git checkout"
    code, out = await _run("git", "log", "-1", "--format=%h %s (%cr)", timeout=10)
    return out if code == 0 else "unknown"


def _mem_mb() -> str:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return f"{int(line.split()[1]) // 1024} MB"
    except OSError:
        pass
    return "n/a"


# ---------- user handlers ----------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_allowed(update):
        await update.message.reply_text(
            f"This is a private bot. Your Telegram user ID is {user.id}.\n"
            "Ask the owner to run /allow with that ID."
        )
        return
    text = "Send or share an Instagram reel link and I'll explain the whole thing."
    if is_admin(update):
        text += "\n\nYou're an admin. /help lists the control commands."
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        log.info("Refused user %s", update.effective_user.id)
        await update.message.reply_text(f"Private bot. Your user ID is {update.effective_user.id}.")
        return

    urls = REEL_URL_RE.findall(update.message.text or "")
    if not urls:
        await update.message.reply_text("Send me an Instagram reel link (instagram.com/reel/...).")
        return
    if settings.get("PAUSED") and not is_admin(update):
        await update.message.reply_text("The bot is paused right now. Try again later.")
        return

    for url in dict.fromkeys(urls):  # dedupe, keep order
        await process_reel(update, context, url)


_job_slots: asyncio.Semaphore | None = None
_job_slots_size = 0
_active_jobs = 0
_stats = {"done": 0, "failed": 0}


def job_slots() -> asyncio.Semaphore:
    """Semaphore sized from MAX_CONCURRENT_JOBS; rebuilt when the setting changes."""
    global _job_slots, _job_slots_size
    size = settings.get("MAX_CONCURRENT_JOBS")
    if _job_slots is None or size != _job_slots_size:
        _job_slots, _job_slots_size = asyncio.Semaphore(size), size
    return _job_slots


async def process_reel(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    global _active_jobs
    slots = job_slots()
    queued = slots.locked()
    status = await update.message.reply_text(
        "Queued, other reels are being processed..." if queued else "Downloading the reel..."
    )
    async with slots:
        if queued:
            await status.edit_text("Downloading the reel...")
        _active_jobs += 1
        try:
            ok = await _process_reel(update, context, url, status)
        finally:
            _active_jobs -= 1
        _stats["done" if ok else "failed"] += 1


async def _process_reel(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, status) -> bool:
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    workdir = Path(tempfile.mkdtemp(prefix="reel_"))
    try:
        try:
            video, info = await asyncio.to_thread(download_reel, url, workdir)
        except yt_dlp.utils.DownloadError as e:
            log.warning("Download failed for %s: %s", url, e)
            hint = "" if cookies_file() else (
                "\n\nInstagram often needs a logged-in session. An admin can send me a cookies.txt file."
            )
            await status.edit_text(f"Couldn't download that reel.{hint}")
            return False
        except Exception:
            log.exception("Unexpected download error for %s", url)
            await status.edit_text("Something went wrong while downloading that reel.")
            return False

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
            return False
        except Exception:
            log.exception("Gemini failed for %s", url)
            await status.edit_text("Gemini failed to explain this reel. Try again later.")
            return False

        await status.delete()
        await reply_long(update, f"{info.get('uploader') or 'Reel'} | {url}\n\n{answer}")
        return True
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------- admin handlers ----------

ADMIN_HELP = """Admin commands

/status - health, version, usage
/config - all settings and where each comes from
/set KEY VALUE - change a setting (saved, survives restarts)
/reset KEY - back to the .env/default value
/prompt - show the Gemini prompt
/setprompt TEXT - replace it (must keep {uploader} and {caption})
/resetprompt - restore the default prompt

/users - allowed users and admins
/allow ID - let a user use the bot
/deny ID - remove a user
/admin ID - make a user an admin
/unadmin ID - remove an admin

/pause, /resume - stop or start accepting reels
/cookies - cookie status. Send a file named cookies.txt to replace it
/logs [N] - last N log lines (default 30)
/update - pull the latest code from GitHub and restart
/restart - restart the bot (also updates yt-dlp)"""


@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ADMIN_HELP)


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cookie = cookies_file()
    cookie_age = (
        f"{_duration(time.time() - Path(cookie).stat().st_mtime)} old" if cookie else "missing"
    )
    text = (
        f"{'PAUSED' if settings.get('PAUSED') else 'Running'}\n"
        f"Version: {await git_version()}\n"
        f"Uptime: {_duration(time.time() - STARTED_AT)}\n"
        f"Host: {platform.node()} ({platform.system()} {platform.machine()})\n"
        f"Memory: {_mem_mb()}\n"
        f"Jobs: {_active_jobs} active, {_stats['done']} done, {_stats['failed']} failed since start\n"
        f"Model: {settings.get('GEMINI_MODEL')} (fallback: {settings.display('GEMINI_FALLBACK_MODELS')})\n"
        f"yt-dlp: {yt_dlp.version.__version__}\n"
        f"Cookies: {cookie_age}"
    )
    await update.message.reply_text(text)


@admin_only
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["Settings (source in brackets). Change with /set KEY VALUE\n"]
    for key, spec in SPECS.items():
        if key == "PROMPT":
            lines.append(f"PROMPT [{settings.source(key)}]: see /prompt")
            continue
        lines.append(f"{key} [{settings.source(key)}]: {settings.display(key)}\n  {spec.help}")
    await reply_long(update, "\n".join(lines))


async def _apply_side_effects(key: str) -> None:
    if key == "LOG_LEVEL":
        logging.getLogger().setLevel(settings.get("LOG_LEVEL"))


@admin_only
async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /set KEY VALUE\nKeys: " + ", ".join(SPECS))
        return
    key = context.args[0].upper()
    raw = " ".join(context.args[1:])
    if key == "PROMPT":
        await update.message.reply_text("Use /setprompt for the prompt.")
        return
    if key not in SPECS:
        await update.message.reply_text(f"Unknown key {key}. Keys: " + ", ".join(SPECS))
        return
    try:
        settings.set(key, raw)
    except (ValueError, TypeError) as e:
        await update.message.reply_text(f"Invalid value for {key}: {e}")
        return
    await _apply_side_effects(key)
    if SPECS[key].secret:  # don't leave secrets sitting in the chat
        try:
            await update.message.delete()
        except TelegramError:
            pass
    log.info("Admin %s set %s", update.effective_user.id, key)
    await update.effective_chat.send_message(f"{key} = {settings.display(key)}")


@admin_only
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1 or context.args[0].upper() not in SPECS:
        await update.message.reply_text("Usage: /reset KEY\nKeys: " + ", ".join(SPECS))
        return
    key = context.args[0].upper()
    settings.reset(key)
    await _apply_side_effects(key)
    log.info("Admin %s reset %s", update.effective_user.id, key)
    shown = "default prompt restored" if key == "PROMPT" else settings.display(key)
    await update.message.reply_text(f"{key} reset: {shown}")


@admin_only
async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_long(update, f"Current prompt [{settings.source('PROMPT')}]:\n\n{settings.get('PROMPT')}")


@admin_only
async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").split(maxsplit=1)
    if len(text) < 2:
        await update.message.reply_text(
            "Usage: /setprompt followed by the full prompt on the next lines. "
            "It must contain {uploader} and {caption}."
        )
        return
    try:
        settings.set("PROMPT", text[1])
    except (ValueError, KeyError, IndexError) as e:
        await update.message.reply_text(f"Prompt not saved: {e}")
        return
    log.info("Admin %s changed the prompt", update.effective_user.id)
    await update.message.reply_text("Prompt saved. It applies to the next reel.")


@admin_only
async def cmd_resetprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings.reset("PROMPT")
    await update.message.reply_text("Default prompt restored.")


@admin_only
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    explicit = settings.get("ADMIN_USER_IDS")
    await update.message.reply_text(
        f"Allowed: {settings.display('ALLOWED_USER_IDS')}\n"
        f"Admins: {', '.join(map(str, sorted(admin_ids()))) or '(none)'}"
        + ("" if explicit else "\n(No explicit admins, so every allowed user is an admin.)")
    )


def _id_command(key: str, add: bool, verb: str):
    @admin_only
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if len(context.args) != 1 or not context.args[0].lstrip("-").isdigit():
            await update.message.reply_text(f"Usage: /{verb} USER_ID")
            return
        uid = int(context.args[0])
        ids = set(settings.get(key))
        if add:
            ids.add(uid)
        else:
            if key == "ADMIN_USER_IDS" and uid == update.effective_user.id and len(admin_ids()) <= 1:
                await update.message.reply_text("You're the last admin; refusing to remove yourself.")
                return
            if key == "ALLOWED_USER_IDS" and uid in admin_ids() and uid == update.effective_user.id:
                await update.message.reply_text("You can't remove your own access.")
                return
            ids.discard(uid)
        if key == "ADMIN_USER_IDS" and add and not settings.get("ADMIN_USER_IDS"):
            # First explicit admin: keep the current implicit admins too, so nobody gets locked out.
            ids |= admin_ids()
        settings.set(key, sorted(ids))
        log.info("Admin %s ran /%s %s", update.effective_user.id, verb, uid)
        await update.message.reply_text(f"Done. {key}: {settings.display(key)}")
        await register_commands(context.application)

    handler.__name__ = f"cmd_{verb}"
    return handler


@admin_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings.set("PAUSED", True)
    await update.message.reply_text("Paused. Non-admins are refused until /resume.")


@admin_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings.set("PAUSED", False)
    await update.message.reply_text("Resumed.")


@admin_only
async def cmd_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    path = cookies_file()
    if path:
        age = _duration(time.time() - Path(path).stat().st_mtime)
        msg = f"Cookies file {path} is present, last replaced {age} ago."
    else:
        msg = "No cookies file. Instagram downloads will often fail."
    await update.message.reply_text(
        msg + "\n\nTo replace it, send me the exported file named cookies.txt as a document."
    )


@admin_only
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if not doc or not (doc.file_name or "").lower().endswith(".txt") or "cookie" not in doc.file_name.lower():
        await update.message.reply_text("Send cookies as a file named cookies.txt.")
        return
    if doc.file_size and doc.file_size > 1_000_000:
        await update.message.reply_text("That file is too big to be a cookies.txt.")
        return
    data = bytes(await (await doc.get_file()).download_as_bytearray())
    text = data.decode("utf-8", errors="replace")
    if "instagram.com" not in text or "\t" not in text:
        await update.message.reply_text(
            "That doesn't look like a Netscape cookies.txt with instagram.com cookies. Not saved."
        )
        return
    target = BASE_DIR / (settings.get("INSTAGRAM_COOKIES_FILE").strip() or "cookies.txt")
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(target)
    try:  # it's a login secret; don't leave it in the chat
        await update.message.delete()
    except TelegramError:
        pass
    log.info("Admin %s replaced the cookies file", update.effective_user.id)
    await update.effective_chat.send_message("Cookies saved and your message deleted. Used from the next reel.")


@admin_only
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = 30
    if context.args and context.args[0].isdigit():
        n = max(1, min(200, int(context.args[0])))
    lines = list(memory_log.lines)[-n:]
    await reply_long(update, "\n".join(lines) or "No log lines yet.")


async def _restart(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data["restart"] = True
    context.application.stop_running()


@admin_only
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _active_jobs:
        await update.message.reply_text(f"{_active_jobs} reel(s) in progress; they'll be cut off.")
    await update.message.reply_text("Restarting. Back in about 20 seconds.")
    log.info("Admin %s requested restart", update.effective_user.id)
    await _restart(context)


@admin_only
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (BASE_DIR / ".git").exists():
        await update.message.reply_text("This install isn't a git checkout, so it can't self-update.")
        return
    msg = await update.message.reply_text("Fetching from GitHub...")
    before = await git_version()
    code, out = await _run("git", "pull", "--ff-only", timeout=120)
    if code != 0:
        log.error("git pull failed: %s", out)
        await msg.edit_text(f"git pull failed:\n{out[-3000:]}")
        return
    if "Already up to date" in out:
        await msg.edit_text(f"Already up to date: {before}")
        return
    await msg.edit_text("Installing requirements...")
    code, pip_out = await _run(sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt", timeout=600)
    if code != 0:
        log.error("pip install failed: %s", pip_out)
        await msg.edit_text(f"Code pulled but pip install failed; not restarting:\n{pip_out[-3000:]}")
        return
    after = await git_version()
    log.info("Updated %s -> %s by admin %s", before, after, update.effective_user.id)
    await msg.edit_text(f"Updated:\n{before}\n->\n{after}\n\nRestarting now.")
    await _restart(context)


# ---------- lifecycle ----------

USER_COMMANDS = [BotCommand("start", "How to use this bot")]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("help", "Admin commands"),
    BotCommand("status", "Health and usage"),
    BotCommand("config", "Show settings"),
    BotCommand("set", "Change a setting"),
    BotCommand("users", "Allowed users and admins"),
    BotCommand("allow", "Allow a user"),
    BotCommand("deny", "Remove a user"),
    BotCommand("prompt", "Show the Gemini prompt"),
    BotCommand("pause", "Stop accepting reels"),
    BotCommand("resume", "Accept reels again"),
    BotCommand("cookies", "Cookie status"),
    BotCommand("logs", "Recent log lines"),
    BotCommand("update", "Pull latest code and restart"),
    BotCommand("restart", "Restart the bot"),
]


async def register_commands(app: Application) -> None:
    try:
        await app.bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
        for uid in admin_ids():
            await app.bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(uid))
    except TelegramError as e:
        log.warning("Could not register command menu: %s", e)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error while handling an update", exc_info=context.error)


async def _post_init(app: Application) -> None:
    me = await app.bot.get_me()
    log.info("Logged in as @%s, version %s", me.username, await git_version())
    await register_commands(app)
    for uid in admin_ids():
        try:
            await app.bot.send_message(uid, f"Bot started. {await git_version()}")
        except TelegramError:
            pass  # admin hasn't opened a chat with the bot yet


_lock_handle = None


def _acquire_single_instance_lock() -> bool:
    """Only one copy may poll Telegram at a time, or both get 409 Conflict errors."""
    global _lock_handle
    _lock_handle = open(BASE_DIR / "bot.lock", "w")  # noqa: SIM115 - held for the process lifetime
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


def build_app() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(_post_init)
        .build()
    )
    app.add_error_handler(on_error)
    commands = {
        "start": start,
        "help": cmd_help,
        "status": cmd_status,
        "config": cmd_config,
        "set": cmd_set,
        "reset": cmd_reset,
        "prompt": cmd_prompt,
        "setprompt": cmd_setprompt,
        "resetprompt": cmd_resetprompt,
        "users": cmd_users,
        "allow": _id_command("ALLOWED_USER_IDS", True, "allow"),
        "deny": _id_command("ALLOWED_USER_IDS", False, "deny"),
        "admin": _id_command("ADMIN_USER_IDS", True, "admin"),
        "unadmin": _id_command("ADMIN_USER_IDS", False, "unadmin"),
        "pause": cmd_pause,
        "resume": cmd_resume,
        "cookies": cmd_cookies,
        "logs": cmd_logs,
        "update": cmd_update,
        "restart": cmd_restart,
    }
    for name, handler in commands.items():
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def main() -> None:
    if not _acquire_single_instance_lock():
        log.error("The bot is already running (auto-start or another window). Exiting.")
        sys.exit(1)
    if not settings.get("ALLOWED_USER_IDS") and not settings.get("ADMIN_USER_IDS"):
        log.warning(
            "ALLOWED_USER_IDS is empty: the bot will refuse everyone. "
            "Message it /start to learn your user ID, then add it to .env."
        )
    log.info("Starting bot with model %s", settings.get("GEMINI_MODEL"))
    app = build_app()
    # bootstrap_retries=-1: at boot the network may not be up yet, so keep retrying instead of exiting.
    app.run_polling(allowed_updates=["message"], bootstrap_retries=-1)
    if app.bot_data.get("restart"):
        log.info("Exiting for restart")
        sys.exit(RESTART_EXIT_CODE)


if __name__ == "__main__":
    main()
