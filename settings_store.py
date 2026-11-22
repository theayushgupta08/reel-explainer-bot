"""Runtime settings that admins can change from Telegram.

Values come from (highest priority first): settings.json (written by /set),
environment / .env, then the defaults below. settings.json is gitignored.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _ids(value: Any) -> list[int]:
    if isinstance(value, list):
        return sorted({int(v) for v in value})
    return sorted({int(x) for x in re.split(r"[,\s]+", str(value or "")) if x.strip()})


def _models(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [m for m in re.split(r"[,\s]+", str(value or "")) if m]


def _bounded_int(lo: int, hi: int):
    def parse(value: Any) -> int:
        n = int(value)
        if not lo <= n <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return n

    return parse


def _level(value: Any) -> str:
    v = str(value).upper()
    if v not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("must be DEBUG, INFO, WARNING or ERROR")
    return v


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    raise ValueError("must be on or off")


def _section_keys(value: Any) -> list[str]:
    from sections import BY_KEY

    keys = value if isinstance(value, list) else [k for k in re.split(r"[,\s]+", str(value or "")) if k]
    bad = [k for k in keys if k not in BY_KEY]
    if bad or not keys:
        raise ValueError("choose from: " + ", ".join(BY_KEY))
    return list(dict.fromkeys(keys))


def _platforms(value: Any) -> list[str]:
    from platforms import BY_KEY

    keys = value if isinstance(value, list) else [k for k in re.split(r"[,\s]+", str(value or "").lower()) if k]
    bad = [k for k in keys if k not in BY_KEY]
    if bad or not keys:
        raise ValueError("choose from: " + ", ".join(BY_KEY))
    return list(dict.fromkeys(keys))


@dataclass(frozen=True)
class Spec:
    default: Any
    parse: Any
    help: str
    secret: bool = False


DEFAULT_PROMPT = """You are watching a video (an Instagram reel, YouTube video or Facebook video).
Watch the full video AND listen to the audio.
Answer ONLY the sections requested below, in the order given. Start each section with its heading
in capitals on its own line. Plain text only, no markdown symbols like ** or #.
Be specific: quote exact numbers, names and claims. If a section doesn't apply, say so in one line.

Requested sections:

{sections}

Context from the post itself:
Creator: {uploader}
Caption: {caption}
"""


def _prompt(value: Any) -> str:
    text = str(value).strip()
    missing = [p for p in ("{uploader}", "{caption}", "{sections}") if p not in text]
    if missing:
        raise ValueError("prompt must contain the placeholders " + ", ".join(missing))
    text.format(uploader="x", caption="x", sections="x")  # fail early on stray braces
    return text


SPECS: dict[str, Spec] = {
    "GEMINI_API_KEY": Spec("", str, "Gemini API key", secret=True),
    "GEMINI_MODEL": Spec("gemini-3.5-flash", str, "Main Gemini model"),
    "GEMINI_FALLBACK_MODELS": Spec(["gemini-3.5-flash-lite"], _models, "Fallback models, comma-separated"),
    "GEMINI_TIMEOUT_S": Spec(90, _bounded_int(10, 600), "Per-call Gemini timeout in seconds"),
    "MAX_CONCURRENT_JOBS": Spec(2, _bounded_int(1, 10), "Reels processed at the same time"),
    "ENABLED_PLATFORMS": Spec(
        ["instagram", "youtube", "facebook"], _platforms, "Which sites' links the bot accepts"
    ),
    "MAX_VIDEO_MIN": Spec(20, _bounded_int(1, 600), "Longest video to explain, in minutes"),
    "MAX_VIDEO_MB": Spec(200, _bounded_int(5, 2000), "Largest video to download, in MB"),
    "ALLOWED_USER_IDS": Spec([], _ids, "Telegram user IDs allowed to use the bot"),
    "ADMIN_USER_IDS": Spec([], _ids, "Telegram user IDs allowed to run admin commands"),
    "INSTAGRAM_COOKIES_FILE": Spec("cookies.txt", str, "Path to cookies.txt (Instagram/Facebook/YouTube logins)"),
    "LOG_LEVEL": Spec("INFO", _level, "DEBUG, INFO, WARNING or ERROR"),
    "DEFAULT_SECTIONS": Spec(
        ["summary", "takeaways", "tools", "steps", "factcheck"], _section_keys,
        "Sections pre-ticked for a user's first reel",
    ),
    "JOB_TTL_MIN": Spec(30, _bounded_int(5, 720), "Minutes a reel stays ready for follow-up questions"),
    "PAUSED": Spec(False, _bool, "When on, the bot refuses new reels"),
    "PROMPT": Spec(DEFAULT_PROMPT, _prompt, "Instructions sent to Gemini (use /prompt)"),
}


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._overrides: dict[str, Any] = {}
        if path.exists():
            try:
                self._overrides = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._overrides = {}

    def get(self, key: str) -> Any:
        spec = SPECS[key]
        if key in self._overrides:
            try:
                return spec.parse(self._overrides[key])
            except (ValueError, TypeError):
                pass  # a saved value that a newer version rejects falls back to env/default
        env = os.getenv(key)
        if env is not None and env.strip() != "":
            return spec.parse(env.strip())
        return spec.default

    def source(self, key: str) -> str:
        if key in self._overrides:
            return "telegram"
        if os.getenv(key, "").strip():
            return "env"
        return "default"

    def set(self, key: str, raw: Any) -> Any:
        if key not in SPECS:
            raise KeyError(key)
        value = SPECS[key].parse(raw)
        with self._lock:
            self._overrides[key] = value
            self._save()
        return value

    def reset(self, key: str) -> None:
        if key not in SPECS:
            raise KeyError(key)
        with self._lock:
            self._overrides.pop(key, None)
            self._save()

    def display(self, key: str) -> str:
        value = self.get(key)
        if SPECS[key].secret:
            return f"…{str(value)[-4:]}" if value else "(not set)"
        if isinstance(value, list):
            return ", ".join(map(str, value)) or "(empty)"
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value)

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._overrides, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)
