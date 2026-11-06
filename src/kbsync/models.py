"""Domain models / dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Article:
    """Raw article from Zendesk API."""
    id: int
    title: str
    body: str
    html_url: str
    locale: str
    draft: bool = False
    section_id: int | None = None
    created_at: str = ""
    updated_at: str = ""
    edited_at: str = ""
    label_names: list[str] = field(default_factory=list)


@dataclass
class DocState:
    """State of a document in the Gemini File Search store."""
    article_id: str
    slug: str
    content_hash: str
    url: str
    updated_at: str
    doc_name: str  # full resource name, e.g. "fileSearchStores/abc/documents/xyz"


@dataclass
class RunStats:
    """Counters for a single run."""
    fetched: int = 0
    skipped_draft: int = 0
    skipped_empty: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    failed: int = 0
    chunks_estimated: int = 0
