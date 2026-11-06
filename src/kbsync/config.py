"""Configuration — reads all settings from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_key: str
    zendesk_base_url: str = "https://support.optisigns.com"
    locale: str = "en-us"
    store_display_name: str = "optibot-support-kb"
    gemini_model: str = "gemini-3.5-flash"
    chunk_tokens: int = 400
    overlap: int = 60
    max_workers: int = 4
    limit: int = 0
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("API_KEY")
        if not api_key:
            raise ValueError(
                "API key not found. Set GEMINI_API_KEY or API_KEY environment variable."
            )
        return cls(
            api_key=api_key,
            zendesk_base_url=os.environ.get("ZENDESK_BASE_URL", "https://support.optisigns.com"),
            locale=os.environ.get("ZENDESK_LOCALE", "en-us"),
            store_display_name=os.environ.get("STORE_DISPLAY_NAME", "optibot-support-kb"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
            chunk_tokens=int(os.environ.get("CHUNK_MAX_TOKENS", "400")),
            overlap=int(os.environ.get("CHUNK_OVERLAP_TOKENS", "60")),
            max_workers=int(os.environ.get("MAX_WORKERS", "4")),
            limit=int(os.environ.get("ARTICLE_LIMIT", "0")),
            dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
        )
