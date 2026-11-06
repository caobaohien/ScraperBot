"""Tests for Config.from_env()."""
from __future__ import annotations

import pytest

from kbsync.config import Config


def test_config_reads_gemini_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    monkeypatch.delenv("API_KEY", raising=False)
    cfg = Config.from_env()
    assert cfg.api_key == "test-key-123"


def test_config_falls_back_to_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "fallback-key")
    cfg = Config.from_env()
    assert cfg.api_key == "fallback-key"


def test_config_raises_when_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key not found"):
        Config.from_env()


def test_config_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    for var in [
        "ZENDESK_BASE_URL", "ZENDESK_LOCALE", "STORE_DISPLAY_NAME",
        "GEMINI_MODEL", "CHUNK_MAX_TOKENS", "CHUNK_OVERLAP_TOKENS",
        "MAX_WORKERS", "ARTICLE_LIMIT", "DRY_RUN",
    ]:
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env()
    assert cfg.locale == "en-us"
    assert cfg.gemini_model == "gemini-3.5-flash"
    assert cfg.chunk_tokens == 400
    assert cfg.overlap == 60
    assert cfg.max_workers == 4
    assert cfg.limit == 0
    assert cfg.dry_run is False
    assert cfg.store_display_name == "optibot-support-kb"


def test_config_dry_run_true(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("DRY_RUN", "true")
    cfg = Config.from_env()
    assert cfg.dry_run is True


def test_config_article_limit(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("ARTICLE_LIMIT", "30")
    cfg = Config.from_env()
    assert cfg.limit == 30

