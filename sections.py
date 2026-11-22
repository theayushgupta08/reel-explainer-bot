"""What a user can ask for about a reel. Each section becomes a button and a prompt instruction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    key: str
    label: str  # button text
    heading: str  # heading Gemini writes in the answer
    instruction: str


SECTIONS: list[Section] = [
    Section("summary", "📝 Summary", "SUMMARY",
            "2-3 sentences on what the reel is about and its main point."),
    Section("takeaways", "💡 Key takeaways", "KEY TAKEAWAYS",
            "The 3-7 most useful insights or action items, as short bullet lines starting with '- '."),
    Section("said", "🗣 What's said", "WHAT'S SAID",
            "The key points from the speech or voiceover, in order, with exact numbers, names and claims. "
            "If there is no speech, say so and describe the audio."),
    Section("transcript", "📜 Full transcript", "TRANSCRIPT",
            "A verbatim transcript of all speech with rough [m:ss] timestamps. "
            "Translate to English in brackets if the speech is in another language."),
    Section("shown", "👀 What's shown", "WHAT'S SHOWN",
            "Important on-screen text, slides, code, products, places or demos that the audio doesn't cover."),
    Section("tools", "🔗 Tools & links", "TOOLS, LINKS & NAMES",
            "Every app, website, product, book, person or account mentioned or shown. For each: what it is, "
            "its website or handle if you know it, and whether it's free, freemium or paid if you know. "
            "Write 'None' if there are none."),
    Section("steps", "🪜 Steps", "STEPS / HOW-TO",
            "The exact steps the reel teaches, numbered, with any settings, prompts or commands shown. "
            "If it doesn't teach steps, say so in one line."),
    Section("factcheck", "✅ Fact check", "FACT CHECK",
            "Flag claims that are misleading, outdated, exaggerated or unverifiable, briefly and honestly, "
            "and say what's actually true where you can. Write 'Nothing notable' if it holds up."),
    Section("recreate", "🎬 Make one with AI", "MAKE A REEL LIKE THIS WITH AI",
            "First describe the format in one or two lines (style, length, shots, voice, captions, music). "
            "Then give a step-by-step workflow to make a similar reel with AI, covering script, voice, visuals or "
            "footage, editing and captions. Give two tracks: FREE (only free tools or free tiers) and PAID "
            "(best results, with rough monthly cost). Name specific tools for each step. "
            "Mention that tool pricing changes often."),
    Section("why", "📈 Why it works", "WHY IT WORKS",
            "Break down the hook in the first 3 seconds, structure, pacing, editing, text style, call to action "
            "and target audience, then list what a creator should copy."),
    Section("audio", "🎵 Music & audio", "MUSIC & AUDIO",
            "Identify the song or sound if you recognise it (say clearly if unsure), plus voice style and sound "
            "effects."),
    Section("ideas", "✍️ Content ideas", "CONTENT IDEAS",
            "5 ideas for original reels inspired by this one, each with a one-line hook."),
]

BY_KEY = {s.key: s for s in SECTIONS}
DEFAULT_KEYS = ["summary", "takeaways", "tools", "steps", "factcheck"]


def ordered(keys) -> list[Section]:
    """Sections for the given keys, in catalogue order, unknown keys dropped."""
    wanted = set(keys)
    return [s for s in SECTIONS if s.key in wanted]


def build_section_block(keys) -> str:
    return "\n\n".join(f"{s.heading}\n{s.instruction}" for s in ordered(keys))
