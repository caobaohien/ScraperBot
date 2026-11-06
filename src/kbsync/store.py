"""Gemini File Search store wrapper for kb-sync.

Handles:
- Creating/finding the named store
- Uploading .md files with custom_metadata and chunking config
- Listing documents and parsing their state (Plan A: metadata / Plan B: display_name encoding)
- Deleting documents
- Estimating chunk counts for logging

Plan A: custom_metadata contains article_id, content_hash, url, updated_at
Plan B fallback: display_name encodes hash as <slug>__<hash8>.md
"""
from __future__ import annotations

import logging
import math
import mimetypes
import time
from typing import TYPE_CHECKING

from kbsync.models import DocState

mimetypes.add_type("text/markdown", ".md")

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 3
_POLL_TIMEOUT_CYCLES = 120  # 6 minutes max


def estimate_chunks(n_tokens: int, max_t: int = 400, overlap: int = 60) -> int:
    """Estimate the number of chunks for a document with white_space_config.

    Args:
        n_tokens: approximate token count (whitespace-split word count)
        max_t: max_tokens_per_chunk
        overlap: max_overlap_tokens
    """
    if n_tokens <= max_t:
        return 1
    return 1 + math.ceil((n_tokens - max_t) / (max_t - overlap))


class KnowledgeStore:
    """Thin wrapper around the Gemini File Search store API."""

    def __init__(
        self,
        api_key: str,
        display_name: str,
        chunk_tokens: int = 400,
        overlap: int = 60,
    ) -> None:
        self.api_key = api_key
        self.display_name = display_name
        self.chunk_tokens = chunk_tokens
        self.overlap = overlap
        self._client = None  # lazy init so unit tests can avoid a real key

    @property
    def client(self):
        if self._client is None:
            from google import genai  # type: ignore[import]
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ------------------------------------------------------------------
    # Store lifecycle
    # ------------------------------------------------------------------

    def get_or_create_store(self) -> str:
        """Return the resource name of the named store, creating it if needed."""
        for store in self.client.file_search_stores.list():
            if store.display_name == self.display_name:
                logger.info("Found existing store: %s", store.name)
                return store.name
        store = self.client.file_search_stores.create(
            config={"display_name": self.display_name}
        )
        logger.info("Created new store: %s", store.name)
        return store.name

    # ------------------------------------------------------------------
    # Document listing & state parsing
    # ------------------------------------------------------------------

    def list_documents(self, store_name: str) -> list:
        """Return raw document objects from the store."""
        return list(self.client.file_search_stores.documents.list(parent=store_name))

    def _parse_doc_state(self, doc) -> DocState | None:
        """Parse a document object into a DocState.

        Tries Plan A (custom_metadata) first, falls back to Plan B (display_name encoding).
        Returns None if the document cannot be parsed.
        """
        try:
            # Plan A: read from custom_metadata list
            meta: dict[str, str] = {}
            for entry in (doc.custom_metadata or []):
                if hasattr(entry, "key") and hasattr(entry, "string_value"):
                    meta[entry.key] = entry.string_value

            if "article_id" in meta and "content_hash" in meta:
                display_name = getattr(doc, "display_name", "") or ""
                # slug is the display_name without extension
                slug = display_name.removesuffix(".md").split("__")[0]
                return DocState(
                    article_id=meta["article_id"],
                    slug=slug,
                    content_hash=meta["content_hash"],
                    url=meta.get("url", ""),
                    updated_at=meta.get("updated_at", ""),
                    doc_name=doc.name,
                )

            # Plan B: decode from display_name "<slug>__<hash8>.md"
            display_name = getattr(doc, "display_name", "") or ""
            stem = display_name.removesuffix(".md")
            if "__" in stem:
                slug, hash8 = stem.rsplit("__", 1)
                # article_id is the numeric prefix of the slug (before first "-")
                article_id = slug.split("-")[0]
                return DocState(
                    article_id=article_id,
                    slug=slug,
                    content_hash=hash8,
                    url="",
                    updated_at="",
                    doc_name=doc.name,
                )

            # Cannot parse — log and skip
            logger.warning("Cannot parse state for document: %s", getattr(doc, "name", "?"))
            return None

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Error parsing document state (%s): %s", getattr(doc, "name", "?"), exc)
            return None

    def read_state(self, store_name: str) -> dict[str, list[DocState]]:
        """Return current store state keyed by article_id.

        dict[article_id -> list[DocState]] — normally 1 doc per article,
        >1 means a previous run crashed between upload and delete (dedupe needed).
        """
        state: dict[str, list[DocState]] = {}
        for doc in self.list_documents(store_name):
            parsed = self._parse_doc_state(doc)
            if parsed is None:
                continue
            state.setdefault(parsed.article_id, []).append(parsed)
        logger.info("Read %d article states from store.", len(state))
        return state

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def _make_display_name(self, slug: str, content_hash: str) -> str:
        """Build display_name supporting both Plan A and Plan B readback."""
        return f"{slug}__{content_hash[:8]}.md"

    def upload(
        self,
        store_name: str,
        path: str,
        slug: str,
        meta: dict,
    ) -> str:
        """Upload a single .md file to the store and poll until done.

        Args:
            store_name: full resource name of the store
            path: local file path to upload
            slug: article slug used for display_name
            meta: dict with keys: id, hash, url, updated_at

        Returns:
            display_name used for this document
        """
        display_name = self._make_display_name(slug, meta["hash"])
        chunk_cfg = {
            "white_space_config": {
                "max_tokens_per_chunk": self.chunk_tokens,
                "max_overlap_tokens": self.overlap,
            }
        }
        upload_config = {
            "display_name": display_name,
            "mime_type": "text/markdown",
            "chunking_config": chunk_cfg,
            "custom_metadata": [
                {"key": "article_id", "string_value": str(meta["id"])},
                {"key": "content_hash", "string_value": meta["hash"]},
                {"key": "url", "string_value": meta.get("url", "")},
                {"key": "updated_at", "string_value": meta.get("updated_at", "")},
            ],
        }

        op = self.client.file_search_stores.upload_to_file_search_store(
            file=path,
            file_search_store_name=store_name,
            config=upload_config,
        )

        # Poll until the long-running operation completes
        for _ in range(_POLL_TIMEOUT_CYCLES):
            if getattr(op, "done", False):
                break
            time.sleep(_POLL_INTERVAL_S)
            try:
                op = self.client.operations.get(op)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Poll error: %s", exc)

        error = getattr(op, "error", None)
        if error:
            raise RuntimeError(f"Upload failed for {slug!r}: {error}")

        logger.info("Uploaded: %s", display_name)
        return display_name

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_document(self, doc_name: str) -> None:
        """Delete a document from the store (force=True required by API)."""
        self.client.file_search_stores.documents.delete(
            name=doc_name, config={"force": True}
        )
        logger.info("Deleted document: %s", doc_name)

