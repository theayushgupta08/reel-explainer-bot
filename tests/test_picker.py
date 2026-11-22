import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ["LOG_FILE"] = ""

from google.genai import types

import bot
from platforms import BY_KEY as PLATFORMS
from sections import SECTIONS, build_section_block


class FakeMsg:
    def __init__(self, sent, text="", markup=None, message_id=1):
        self.sent, self.text, self.reply_markup, self.message_id = sent, text, markup, message_id

    async def reply_text(self, text, reply_markup=None, **_):
        m = FakeMsg(self.sent, text, reply_markup)
        self.sent.append(m)
        return m

    async def edit_text(self, text, reply_markup=None, **_):
        self.text, self.reply_markup = text, reply_markup

    async def edit_reply_markup(self, reply_markup=None):
        self.reply_markup = reply_markup

    async def delete(self):
        self.text = "<deleted>"


class FakeBot:
    def __init__(self, sent):
        self.sent = sent

    async def send_message(self, chat_id, text, reply_markup=None, **_):
        m = FakeMsg(self.sent, text, reply_markup)
        self.sent.append(m)
        return m

    async def send_chat_action(self, *_):
        pass


class FakeQuery:
    def __init__(self, data, user_id, message):
        self.data, self.from_user, self.message = data, SimpleNamespace(id=user_id), message
        self.answers = []

    async def answer(self, text=None, **_):
        self.answers.append(text)


def test_callback_data_fits_telegram_limit():
    job = bot.ReelJob("abcd1234", "u", PLATFORMS["instagram"], 1, 1, 1, [s.key for s in SECTIONS])
    for row in bot.picker_keyboard(job).inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64


def test_prompt_contains_only_selected_sections():
    prompt = bot.build_prompt({"uploader": "me", "description": "cap"}, ["factcheck", "summary"])
    assert "FACT CHECK" in prompt and "SUMMARY" in prompt and "TRANSCRIPT" not in prompt
    assert prompt.index("SUMMARY") < prompt.index("FACT CHECK")  # catalogue order
    assert build_section_block([]) == ""


def test_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(bot, "download_reel", lambda url, wd: (wd / "reel.mp4", {"uploader": "creator"}))
    monkeypatch.setattr(bot, "upload_video", lambda v: "gemini-file")
    monkeypatch.setattr(bot, "delete_uploaded", lambda f: None)
    asked = []
    monkeypatch.setattr(bot, "explain_sections", lambda f, info, keys: asked.append(keys) or f"answer {keys}")
    monkeypatch.setattr(bot, "is_allowed", lambda u: True)

    async def scenario():
        sent = []
        user_msg = FakeMsg(sent, "https://www.instagram.com/reel/ABC/")
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=7), effective_chat=SimpleNamespace(id=7), message=user_msg
        )
        ctx = SimpleNamespace(bot=FakeBot(sent), args=[])
        await bot.handle_message(update, ctx)
        job = next(iter(bot.jobs.values()))
        picker = job.picker_msg
        await job.ready.wait()
        await asyncio.sleep(0)

        async def press(data, msg=picker, user=7):
            q = FakeQuery(data, user, msg)
            await bot.on_button(SimpleNamespace(callback_query=q), ctx)
            return q

        assert "Pre-ticked from the defaults (5)" in picker.text
        await press(f"none|{job.id}")
        assert "Nothing ticked yet" in picker.text
        q = await press(f"go|{job.id}")
        assert q.answers == ["Pick at least one option."]
        await press(f"t|{job.id}|recreate")
        await press(f"t|{job.id}|summary")
        q = await press(f"t|{job.id}|summary", user=99)
        assert "Only the person" in q.answers[0]
        await press(f"go|{job.id}")
        assert asked[-1] == ["summary", "recreate"]
        assert any("answer ['summary', 'recreate']" in m.text for m in sent)
        assert bot.user_sections(7) == (["summary", "recreate"], "your last reel")  # remembered for next time

        more = job.more_msg
        labels = [b.callback_data for row in more.reply_markup.inline_keyboard for b in row]
        assert f"m|{job.id}|recreate" not in labels
        await press(f"m|{job.id}|factcheck", msg=more)
        assert asked[-1] == ["factcheck"]

        await bot.expire_job(job, delay=0)
        q = await press(f"m|{job.id}|tools", msg=job.more_msg)
        assert "expired" in q.answers[0]

    asyncio.run(scenario())


def test_youtube_uses_gemini_url_without_download(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(bot, "is_allowed", lambda u: True)
    monkeypatch.setattr(bot, "video_metadata", lambda url: {"title": "T", "uploader": "C", "duration": 60})

    def no_download(*a):
        raise AssertionError("YouTube must not be downloaded")

    monkeypatch.setattr(bot, "download_reel", no_download)
    monkeypatch.setattr(bot, "upload_video", no_download)
    seen = {}

    def fake_explain(uploaded, info, keys):
        seen["uploaded"], seen["prompt"] = uploaded, bot.build_prompt(info, keys)
        return "ok"

    monkeypatch.setattr(bot, "explain_sections", fake_explain)

    async def scenario():
        sent = []
        msg = FakeMsg(sent, "https://youtube.com/shorts/abcDEF12345?si=x")
        u = SimpleNamespace(id=8)
        update = SimpleNamespace(effective_user=u, effective_chat=u, message=msg)
        ctx = SimpleNamespace(bot=FakeBot(sent), args=[])
        await bot.handle_message(update, ctx)
        job = next(j for j in bot.jobs.values() if j.user_id == 8)
        await job.ready.wait()
        assert job.error is None
        assert "YouTube video" in job.picker_msg.text
        q = FakeQuery(f"go|{job.id}", 8, job.picker_msg)
        await bot.on_button(SimpleNamespace(callback_query=q), ctx)
        part = seen["uploaded"]
        assert isinstance(part, types.Part)
        assert part.file_data.file_uri == "https://www.youtube.com/watch?v=abcDEF12345"
        assert "C on YouTube" in seen["prompt"] and "Title: T" in seen["prompt"]
        await bot.expire_job(job, delay=0)

    asyncio.run(scenario())


def test_too_long_youtube_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(bot, "is_allowed", lambda u: True)
    monkeypatch.setattr(bot, "video_metadata", lambda url: {"duration": 3 * 3600})

    async def scenario():
        sent = []
        msg = FakeMsg(sent, "https://youtu.be/dQw4w9WgXcQ")
        u = SimpleNamespace(id=9)
        update = SimpleNamespace(effective_user=u, effective_chat=u, message=msg)
        await bot.handle_message(update, SimpleNamespace(bot=FakeBot(sent), args=[]))
        picker = sent[0]
        for _ in range(50):
            if "limit is" in picker.text:
                break
            await asyncio.sleep(0.01)
        assert "180 min long; the limit is 20 min" in picker.text
        assert not any(j.user_id == 9 for j in bot.jobs.values())

    asyncio.run(scenario())
