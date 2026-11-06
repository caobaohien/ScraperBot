"""Tests for KnowledgeStore — estimate_chunks and state parsing."""
from __future__ import annotations

import math

from kbsync.store import KnowledgeStore, estimate_chunks

# ---------------------------------------------------------------------------
# estimate_chunks
# ---------------------------------------------------------------------------

def test_estimate_chunks_single_tiny():
    assert estimate_chunks(100, max_t=400, overlap=60) == 1


def test_estimate_chunks_at_boundary():
    assert estimate_chunks(400, max_t=400, overlap=60) == 1


def test_estimate_chunks_one_over():
    # 401 tokens → needs a 2nd chunk
    assert estimate_chunks(401, max_t=400, overlap=60) == 2


def test_estimate_chunks_formula():
    n = 1200
    expected = 1 + math.ceil((1200 - 400) / (400 - 60))
    assert estimate_chunks(n) == expected


def test_estimate_chunks_zero():
    # Edge: 0 tokens → 1 chunk (no division by zero)
    assert estimate_chunks(0, max_t=400, overlap=60) == 1


# ---------------------------------------------------------------------------
# _parse_doc_state — Plan A (custom_metadata)
# ---------------------------------------------------------------------------

def _make_meta_entry(key: str, value: str):
    """Create a minimal metadata entry object."""
    class Entry:
        pass
    e = Entry()
    e.key = key
    e.string_value = value
    return e


def _make_doc(name: str, display_name: str, metadata_items: list):
    class Doc:
        pass
    d = Doc()
    d.name = name
    d.display_name = display_name
    d.custom_metadata = metadata_items
    return d


def test_parse_state_plan_a_full():
    store = KnowledgeStore.__new__(KnowledgeStore)
    doc = _make_doc(
        name="fileSearchStores/abc/documents/doc1",
        display_name="360001-my-article.md",
        metadata_items=[
            _make_meta_entry("article_id", "360001"),
            _make_meta_entry("content_hash", "aabbccddee112233"),
            _make_meta_entry("url", "https://support.optisigns.com/hc/en-us/articles/360001"),
            _make_meta_entry("updated_at", "2024-01-01"),
        ],
    )
    state = store._parse_doc_state(doc)
    assert state is not None
    assert state.article_id == "360001"
    assert state.content_hash == "aabbccddee112233"
    assert state.url == "https://support.optisigns.com/hc/en-us/articles/360001"
    assert state.doc_name == "fileSearchStores/abc/documents/doc1"


# ---------------------------------------------------------------------------
# _parse_doc_state — Plan B (display_name encoding)
# ---------------------------------------------------------------------------

def test_parse_state_plan_b_display_name():
    store = KnowledgeStore.__new__(KnowledgeStore)
    doc = _make_doc(
        name="fileSearchStores/abc/documents/doc2",
        display_name="360001-my-article__aabbccdd.md",
        metadata_items=[],  # no metadata → Plan B
    )
    state = store._parse_doc_state(doc)
    assert state is not None
    assert state.content_hash == "aabbccdd"
    assert state.slug == "360001-my-article"


def test_parse_state_plan_b_article_id_from_slug_prefix():
    store = KnowledgeStore.__new__(KnowledgeStore)
    doc = _make_doc(
        name="stores/x/documents/d3",
        display_name="12345-some-article__deadbeef.md",
        metadata_items=[],
    )
    state = store._parse_doc_state(doc)
    assert state is not None
    assert state.article_id == "12345"


def test_parse_state_returns_none_on_unparseable():
    store = KnowledgeStore.__new__(KnowledgeStore)
    doc = _make_doc(
        name="stores/x/documents/d4",
        display_name="no-double-underscore.md",  # no __ → cannot parse Plan B
        metadata_items=[],
    )
    state = store._parse_doc_state(doc)
    assert state is None

