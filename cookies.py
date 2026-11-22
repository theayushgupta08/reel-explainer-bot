"""Merge Netscape cookies.txt files so adding Facebook cookies doesn't wipe Instagram's."""

from __future__ import annotations

HEADER = (
    "# Netscape HTTP Cookie File\n"
    "# Managed by reel-explainer-bot. Each site's cookies replace that site's old ones.\n"
)


def _site(domain: str, known: list[str]) -> str | None:
    d = domain.lstrip(".").lower()
    for site in known:
        if d == site or d.endswith("." + site):
            return site
    return None


def _cookie_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        if line.startswith("#HttpOnly_"):
            lines.append(line)  # HttpOnly cookies are written with this prefix
        elif line.strip() and not line.startswith("#") and len(line.split("\t")) >= 7:
            lines.append(line)
    return lines


def _domain(line: str) -> str:
    return line.split("\t", 1)[0].removeprefix("#HttpOnly_")


def merge_cookies(old: str, new: str, known_sites: list[str]) -> tuple[str, list[str]]:
    """Return the merged file and the sites updated from `new`.

    Only cookies for known sites are kept from the new file. A site present in the new
    file replaces all of that site's old cookies; other sites' old cookies stay.
    """
    incoming = [ln for ln in _cookie_lines(new) if _site(_domain(ln), known_sites)]
    if not incoming:
        raise ValueError(
            "no cookies for " + ", ".join(known_sites) + " found. Export a Netscape-format cookies.txt."
        )
    updated = sorted({_site(_domain(ln), known_sites) for ln in incoming})
    kept = [
        ln for ln in _cookie_lines(old)
        if (s := _site(_domain(ln), known_sites)) and s not in updated
    ]
    return HEADER + "\n".join(kept + incoming) + "\n", updated
