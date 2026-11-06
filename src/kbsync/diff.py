"""Delta computation — determines which articles need to be added, updated, skipped, or deleted."""
from __future__ import annotations

from kbsync.models import DocState


def compute_delta(
    local: dict[str, dict],
    remote: dict[str, list[DocState]],
) -> dict:
    """Compare local scraped articles against remote store state.

    Args:
        local: dict[article_id -> {"slug": str, "hash": str, "meta": dict, "content": str}]
        remote: dict[article_id -> list[DocState]] from KnowledgeStore.read_state()

    Returns:
        {
            "added":   set[article_id],               # in local, not in remote
            "updated": dict[article_id -> list[DocState]],  # in both, hash differs; value = old docs to delete after upload
            "skipped": set[article_id],               # in both, hash matches
            "deleted": dict[article_id -> list[DocState]],  # in remote, not in local
            "dedupe":  dict[article_id -> list[DocState]],  # multiple docs for same article (crash recovery)
        }
    """
    local_ids = set(local.keys())
    remote_ids = set(remote.keys())

    added: set[str] = set()
    updated: dict[str, list[DocState]] = {}
    skipped: set[str] = set()
    deleted: dict[str, list[DocState]] = {}
    dedupe: dict[str, list[DocState]] = {}

    # Articles in local but not in remote → add
    for aid in local_ids - remote_ids:
        added.add(aid)

    # Articles in both → compare hashes
    for aid in local_ids & remote_ids:
        docs = remote[aid]
        local_hash = local[aid]["hash"]

        # Dedupe: more than one doc for the same article (crash recovery)
        if len(docs) > 1:
            matching = [d for d in docs if d.content_hash == local_hash]
            stale = [d for d in docs if d.content_hash != local_hash]
            if matching:
                # Current content already uploaded; just clean up stale copies
                skipped.add(aid)
                if stale:
                    dedupe[aid] = stale
            else:
                # None matches — treat as update (upload new, delete all old)
                updated[aid] = docs
            continue

        doc = docs[0]
        if doc.content_hash == local_hash:
            skipped.add(aid)
        else:
            updated[aid] = [doc]

    # Articles in remote but not in local → delete (article removed or made draft)
    for aid in remote_ids - local_ids:
        deleted[aid] = remote[aid]

    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "deleted": deleted,
        "dedupe": dedupe,
    }

