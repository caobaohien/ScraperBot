"""Tests for the delta computation (diff.py)."""
from __future__ import annotations

from kbsync.diff import compute_delta
from kbsync.models import DocState


def _doc(article_id: str, slug: str, content_hash: str) -> DocState:
    return DocState(
        article_id=article_id,
        slug=slug,
        content_hash=content_hash,
        url="https://x.com",
        updated_at="2024-01-01",
        doc_name=f"stores/x/documents/{slug}",
    )


def _local(article_id: str, slug: str, content_hash: str) -> dict:
    return {"slug": slug, "hash": content_hash, "meta": {}, "content": "# Title\n\nbody\n"}


# ---------------------------------------------------------------------------
# Basic cases
# ---------------------------------------------------------------------------

def test_added_when_only_in_local():
    local = {"1": _local("1", "1-a", "abc123")}
    remote: dict = {}
    delta = compute_delta(local, remote)
    assert "1" in delta["added"]
    assert "1" not in delta["skipped"]
    assert "1" not in delta["updated"]


def test_skipped_when_hash_matches():
    local = {"1": _local("1", "1-a", "abc123")}
    remote = {"1": [_doc("1", "1-a", "abc123")]}
    delta = compute_delta(local, remote)
    assert "1" in delta["skipped"]
    assert "1" not in delta["added"]
    assert "1" not in delta["updated"]


def test_updated_when_hash_differs():
    local = {"1": _local("1", "1-a", "newhash")}
    remote = {"1": [_doc("1", "1-a", "oldhash")]}
    delta = compute_delta(local, remote)
    assert "1" in delta["updated"]
    assert "1" not in delta["skipped"]
    assert "1" not in delta["added"]


def test_deleted_when_only_in_remote():
    local: dict = {}
    remote = {"1": [_doc("1", "1-a", "abc123")]}
    delta = compute_delta(local, remote)
    assert "1" in delta["deleted"]
    assert "1" not in delta["added"]


# ---------------------------------------------------------------------------
# Dedupe (multiple docs for same article)
# ---------------------------------------------------------------------------

def test_dedupe_keeps_matching_skips_stale():
    """When >1 doc and one matches local hash → skipped, stale added to dedupe."""
    local = {"1": _local("1", "1-a", "current")}
    remote = {
        "1": [
            _doc("1", "1-a", "current"),   # matches
            _doc("1", "1-a-old", "stale"),  # stale from old crash
        ]
    }
    delta = compute_delta(local, remote)
    assert "1" in delta["skipped"]
    assert "1" in delta["dedupe"]
    assert len(delta["dedupe"]["1"]) == 1
    assert delta["dedupe"]["1"][0].content_hash == "stale"


def test_dedupe_no_match_treated_as_update():
    """When >1 doc and none matches local hash → updated."""
    local = {"1": _local("1", "1-a", "brandnew")}
    remote = {
        "1": [
            _doc("1", "1-a", "old1"),
            _doc("1", "1-a2", "old2"),
        ]
    }
    delta = compute_delta(local, remote)
    assert "1" in delta["updated"]
    assert len(delta["updated"]["1"]) == 2


# ---------------------------------------------------------------------------
# Mixed scenario
# ---------------------------------------------------------------------------

def test_mixed_scenario():
    local = {
        "1": _local("1", "1-a", "hash1"),  # skipped
        "2": _local("2", "2-b", "new2"),   # updated
        "3": _local("3", "3-c", "hash3"),  # added
    }
    remote = {
        "1": [_doc("1", "1-a", "hash1")],
        "2": [_doc("2", "2-b", "old2")],
        "4": [_doc("4", "4-d", "hash4")],  # deleted
    }
    delta = compute_delta(local, remote)
    assert "1" in delta["skipped"]
    assert "2" in delta["updated"]
    assert "3" in delta["added"]
    assert "4" in delta["deleted"]

