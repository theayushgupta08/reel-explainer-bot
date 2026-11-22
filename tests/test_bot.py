import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ["LOG_FILE"] = ""

import bot


def test_reel_regex_matches_common_links():
    text = "look https://www.instagram.com/reel/ABC_12-x/?igsh=xyz and https://instagram.com/p/Q1/"
    assert len(bot.REEL_URL_RE.findall(text)) == 2


def test_reel_regex_ignores_other_links():
    assert not bot.REEL_URL_RE.findall("https://youtube.com/watch?v=1")


def test_split_respects_limit():
    text = "\n".join(f"line {i} " * 20 for i in range(500))
    chunks = bot._split(text, 1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
