import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ["LOG_FILE"] = ""

import bot
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
    job = bot.ReelJob("abcd1234", "u", 1, 1, 1, [s.key for s in SECTIONS])
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

        await press(f"none|{job.id}")
        q = await press(f"go|{job.id}")
        assert q.answers == ["Pick at least one option."]
        await press(f"t|{job.id}|recreate")
        await press(f"t|{job.id}|summary")
        q = await press(f"t|{job.id}|summary", user=99)
        assert "Only the person" in q.answers[0]
        await press(f"go|{job.id}")
        assert asked[-1] == ["summary", "recreate"]
        assert any("answer ['summary', 'recreate']" in m.text for m in sent)
        assert bot.user_sections(7) == ["summary", "recreate"]  # remembered for next time

        more = job.more_msg
        labels = [b.callback_data for row in more.reply_markup.inline_keyboard for b in row]
        assert f"m|{job.id}|recreate" not in labels
        await press(f"m|{job.id}|factcheck", msg=more)
        assert asked[-1] == ["factcheck"]

        await bot.expire_job(job, delay=0)
        q = await press(f"m|{job.id}|tools", msg=job.more_msg)
        assert "expired" in q.answers[0]

    asyncio.run(scenario())
