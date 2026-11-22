"""Which video links the bot understands, and how each platform is handled."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    pattern: re.Pattern
    # "download": fetch with yt-dlp and upload to Gemini. "gemini_url": Gemini reads the public URL itself.
    mode: str
    cookie_domain: str


PLATFORMS: list[Platform] = [
    Platform(
        "instagram", "Instagram",
        re.compile(r"https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/[\w-]+[^\s]*", re.I),
        "download", "instagram.com",
    ),
    Platform(
        "youtube", "YouTube",
        re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com/(?:shorts/|live/|embed/|watch\?(?:[^\s]*?&)?v=)"
            r"|youtu\.be/)[\w-]{6,}[^\s]*",
            re.I,
        ),
        "gemini_url", "youtube.com",
    ),
    Platform(
        "facebook", "Facebook",
        re.compile(
            r"https?://(?:(?:www|m|web)\.)?(?:facebook\.com/(?:reel/|share/[rv]/|watch/?\?[^\s]*v=|[\w.]+/videos/)"
            r"|fb\.watch/)[^\s]+",
            re.I,
        ),
        "download", "facebook.com",
    ),
]
BY_KEY = {p.key: p for p in PLATFORMS}

_YT_ID = re.compile(r"(?:shorts/|live/|embed/|youtu\.be/|[?&]v=)([\w-]{6,})", re.I)


def find_videos(text: str, enabled=None) -> list[tuple[str, Platform]]:
    """Every supported video link in the text, in order, deduplicated."""
    allowed = set(enabled) if enabled is not None else set(BY_KEY)
    found: list[tuple[int, str, Platform]] = []
    for p in PLATFORMS:
        for m in p.pattern.finditer(text or ""):
            found.append((m.start(), m.group(0).rstrip(".,!?)\"'"), p))
    seen, out = set(), []
    for _, url, p in sorted(found, key=lambda f: f[0]):
        if url not in seen and p.key in allowed:
            seen.add(url)
            out.append((url, p))
    return out


def unsupported_platforms(text: str, enabled) -> list[Platform]:
    """Supported-but-disabled platforms linked in the text (to explain why nothing happened)."""
    return [p for url, p in find_videos(text) if p.key not in set(enabled)]


def canonical_youtube(url: str) -> str:
    """Gemini accepts youtube.com/watch?v= links; turn Shorts and youtu.be links into that form."""
    m = _YT_ID.search(url)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else url
