import os

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ["LOG_FILE"] = ""

import bot
from cookies import merge_cookies
from platforms import canonical_youtube, find_videos, unsupported_platforms


@pytest.mark.parametrize(
    "url,platform",
    [
        ("https://www.instagram.com/reel/ABC_12-x/?igsh=xyz", "instagram"),
        ("https://instagram.com/p/Q1/", "instagram"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ", "youtube"),
        ("https://youtube.com/shorts/abcDEF12345?si=x", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://www.facebook.com/reel/1234567890", "facebook"),
        ("https://www.facebook.com/share/r/1AbCdEf/", "facebook"),
        ("https://www.facebook.com/share/v/1AbCdEf/", "facebook"),
        ("https://www.facebook.com/somepage/videos/1234567890/", "facebook"),
        ("https://www.facebook.com/watch/?v=1234567890", "facebook"),
        ("https://fb.watch/aBcDeF/", "facebook"),
    ],
)
def test_detects_supported_links(url, platform):
    found = find_videos(f"check this {url} out")
    assert [(u, p.key) for u, p in found] == [(url, platform)]


@pytest.mark.parametrize(
    "text",
    ["https://youtube.com/@channel", "https://www.facebook.com/somepage", "https://example.com/reel/1", "no link"],
)
def test_ignores_non_video_links(text):
    assert find_videos(text) == []


def test_multiple_links_keep_order_and_dedupe():
    text = "https://youtu.be/AAAAAAA1 https://www.instagram.com/reel/X/ https://youtu.be/AAAAAAA1."
    assert [p.key for _, p in find_videos(text)] == ["youtube", "instagram"]


def test_disabled_platforms():
    text = "https://fb.watch/aBcDeF/"
    assert find_videos(text, ["instagram", "youtube"]) == []
    assert [p.key for p in unsupported_platforms(text, ["instagram"])] == ["facebook"]


def test_canonical_youtube():
    assert canonical_youtube("https://youtube.com/shorts/abcDEF12345?si=x") == (
        "https://www.youtube.com/watch?v=abcDEF12345"
    )
    assert canonical_youtube("https://youtu.be/dQw4w9WgXcQ?t=5") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_length_limit(monkeypatch):
    monkeypatch.setattr(bot.settings, "get", lambda k: 20 if k == "MAX_VIDEO_MIN" else None)
    bot._check_length({"duration": 20 * 60})
    bot._check_length({})  # unknown length is allowed
    with pytest.raises(bot.VideoTooLong):
        bot._check_length({"duration": 21 * 60})


def _c(domain, name):
    return f"{domain}\tTRUE\t/\tTRUE\t0\t{name}\tv"


def test_cookie_merge_keeps_other_sites():
    old = "\n".join([_c(".instagram.com", "ig"), _c(".facebook.com", "old_fb")])
    new = "\n".join([_c(".facebook.com", "new_fb"), "#HttpOnly_" + _c(".facebook.com", "xs"), _c(".evil.com", "x")])
    merged, sites = merge_cookies(old, new, ["instagram.com", "youtube.com", "facebook.com"])
    assert sites == ["facebook.com"]
    assert "\tig\t" in merged and "new_fb" in merged and "#HttpOnly_.facebook.com" in merged
    assert "old_fb" not in merged and "evil" not in merged


def test_cookie_merge_rejects_junk():
    with pytest.raises(ValueError):
        merge_cookies("", "not a cookie file", ["instagram.com"])


def test_split_respects_limit():
    text = "\n".join(f"line {i} " * 20 for i in range(500))
    chunks = bot._split(text, 1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_youtube_part_caps_unknown_length(monkeypatch):
    monkeypatch.setattr(bot.settings, "get", lambda k: 20 if k == "MAX_VIDEO_MIN" else None)
    capped = bot.youtube_part("https://youtu.be/dQw4w9WgXcQ", {})
    assert capped.video_metadata.end_offset == "1200s"
    assert capped.file_data.file_uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert bot.youtube_part("https://youtu.be/dQw4w9WgXcQ", {"duration": 60}).video_metadata is None
