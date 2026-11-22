import pytest

from settings_store import Settings


def test_override_beats_env_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "4")
    s = Settings(tmp_path / "s.json")
    assert s.get("MAX_CONCURRENT_JOBS") == 4
    assert s.source("MAX_CONCURRENT_JOBS") == "env"
    s.set("MAX_CONCURRENT_JOBS", "1")
    assert Settings(tmp_path / "s.json").get("MAX_CONCURRENT_JOBS") == 1
    s.reset("MAX_CONCURRENT_JOBS")
    assert s.get("MAX_CONCURRENT_JOBS") == 4


def test_validation(tmp_path):
    s = Settings(tmp_path / "s.json")
    with pytest.raises(ValueError):
        s.set("MAX_CONCURRENT_JOBS", "99")
    with pytest.raises(ValueError):
        s.set("PROMPT", "{uploader} {caption} only")
    with pytest.raises(KeyError):
        s.set("NOPE", "1")


def test_id_lists_and_secret_display(tmp_path):
    s = Settings(tmp_path / "s.json")
    s.set("ALLOWED_USER_IDS", "3, 1 2")
    assert s.get("ALLOWED_USER_IDS") == [1, 2, 3]
    s.set("GEMINI_API_KEY", "AIzaSECRET1234")
    assert s.display("GEMINI_API_KEY") == "…1234"
    s.set("PAUSED", "on")
    assert s.get("PAUSED") is True
