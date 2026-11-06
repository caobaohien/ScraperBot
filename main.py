#!/usr/bin/env python3
"""main.py — Entrypoint for Docker/Render cron: scrape → diff → upload → report.

Supports both GEMINI_API_KEY and API_KEY env vars (spec requirement).
Exit code: 0 = success, 1 = any upload failure.
"""
from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Allow running directly (python main.py) without pip install
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kbsync.config import Config
from kbsync.convert import build_markdown, slug_from_url
from kbsync.diff import compute_delta
from kbsync.logging_setup import setup_logging
from kbsync.models import RunStats
from kbsync.report import emit_summary
from kbsync.store import KnowledgeStore, estimate_chunks
from kbsync.zendesk import ZendeskClient

logger = logging.getLogger(__name__)

_MAX_UPLOAD_RETRIES = 3


def _upload_with_retry(
    store: KnowledgeStore,
    store_name: str,
    slug: str,
    content: str,
    meta: dict,
    tmp_dir: Path,
    dry_run: bool,
) -> tuple[bool, int]:
    """Write content to a temp file, upload with retry. Returns (success, estimated_chunks)."""
    n_tokens = len(content.split())
    chunks = estimate_chunks(n_tokens, store.chunk_tokens, store.overlap)

    if dry_run:
        logger.info("[DRY-RUN] Would upload: %s (~%d chunks)", slug, chunks)
        return True, chunks

    tmp_path = tmp_dir / f"{slug}.md"
    tmp_path.write_text(content, encoding="utf-8")

    for attempt in range(_MAX_UPLOAD_RETRIES):
        try:
            store.upload(store_name, str(tmp_path), slug, meta)
            return True, chunks
        except Exception as exc:  # pylint: disable=broad-except
            wait = 2 ** attempt + attempt * 0.3
            logger.warning(
                "Upload failed for %s (attempt %d/%d): %s. Retrying in %.1fs...",
                slug, attempt + 1, _MAX_UPLOAD_RETRIES, exc, wait,
            )
            if attempt < _MAX_UPLOAD_RETRIES - 1:
                time.sleep(wait)

    logger.error("Upload permanently failed: %s", slug)
    return False, 0


def main() -> int:
    setup_logging()
    t0 = time.time()

    cfg = Config.from_env()
    stats = RunStats()

    # -------------------------------------------------------------------------
    # 1. Scrape + convert (in-memory)
    # -------------------------------------------------------------------------
    logger.info("Scraping articles from %s (locale=%s)…", cfg.zendesk_base_url, cfg.locale)
    zd = ZendeskClient(cfg.zendesk_base_url, cfg.locale)

    sections: dict[int, str] = {}
    try:
        sections = zd.get_sections()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Could not load sections: %s", exc)

    local: dict[str, dict] = {}  # article_id (str) -> {slug, hash, content, meta}

    for article in zd.iter_articles():
        stats.fetched += 1

        if article.get("draft"):
            stats.skipped_draft += 1
            continue

        body = (article.get("body") or "").strip()
        from bs4 import BeautifulSoup
        plain = BeautifulSoup(body, "html.parser").get_text(strip=True)
        if len(plain) < 50:
            stats.skipped_empty += 1
            continue

        section_label = sections.get(article.get("section_id", 0))
        content, content_hash = build_markdown(article, section=section_label)
        slug = slug_from_url(article["html_url"])
        article_id = str(article["id"])

        local[article_id] = {
            "slug": slug,
            "hash": content_hash,
            "content": content,
            "meta": {
                "id": article["id"],
                "hash": content_hash,
                "url": article["html_url"],
                "updated_at": article.get("updated_at", ""),
            },
        }

        if cfg.limit and len(local) >= cfg.limit:
            logger.info("Article limit %d reached.", cfg.limit)
            break

    logger.info(
        "Scraped: fetched=%d, valid=%d, skipped_draft=%d, skipped_empty=%d",
        stats.fetched, len(local), stats.skipped_draft, stats.skipped_empty,
    )

    # -------------------------------------------------------------------------
    # 2. Connect to store + read current state
    # -------------------------------------------------------------------------
    store = KnowledgeStore(
        api_key=cfg.api_key,
        display_name=cfg.store_display_name,
        chunk_tokens=cfg.chunk_tokens,
        overlap=cfg.overlap,
    )

    store_name = store.get_or_create_store()
    logger.info("Store: %s", store_name)

    remote = store.read_state(store_name)

    # -------------------------------------------------------------------------
    # 3. Compute delta
    # -------------------------------------------------------------------------
    delta = compute_delta(local, remote)
    logger.info(
        "Delta: added=%d, updated=%d, skipped=%d, deleted=%d, dedupe=%d",
        len(delta["added"]),
        len(delta["updated"]),
        len(delta["skipped"]),
        len(delta["deleted"]),
        len(delta.get("dedupe", {})),
    )

    # -------------------------------------------------------------------------
    # 4. Apply: upload new/changed BEFORE deleting old (crash safety)
    # -------------------------------------------------------------------------
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # Articles to upload: added + updated
        to_upload: list[str] = list(delta["added"]) + list(delta["updated"].keys())

        if to_upload and not cfg.dry_run:
            logger.info("Uploading %d articles (workers=%d)…", len(to_upload), cfg.max_workers)

        def _do_upload(article_id: str) -> tuple[str, bool, int]:
            art = local[article_id]
            ok, chunks = _upload_with_retry(
                store, store_name,
                art["slug"], art["content"], art["meta"],
                tmp_dir, cfg.dry_run,
            )
            return article_id, ok, chunks

        with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
            futures = {executor.submit(_do_upload, aid): aid for aid in to_upload}
            for fut in as_completed(futures):
                aid, ok, chunks = fut.result()
                if ok:
                    if aid in delta["added"]:
                        stats.added += 1
                    else:
                        stats.updated += 1
                    stats.chunks_estimated += chunks
                else:
                    stats.failed += 1

        stats.skipped = len(delta["skipped"])

        # Delete stale docs (only after successful uploads)
        docs_to_delete: list = []
        for docs in delta["deleted"].values():
            docs_to_delete.extend(docs)
        for docs in delta["updated"].values():
            docs_to_delete.extend(docs)   # old version
        for docs in delta.get("dedupe", {}).values():
            docs_to_delete.extend(docs)

        for doc in docs_to_delete:
            if cfg.dry_run:
                logger.info("[DRY-RUN] Would delete: %s", doc.doc_name)
                stats.deleted += 1
            else:
                try:
                    store.delete_document(doc.doc_name)
                    stats.deleted += 1
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Delete failed for %s: %s", doc.doc_name, exc)
                    stats.failed += 1

    # -------------------------------------------------------------------------
    # 5. Report
    # -------------------------------------------------------------------------
    emit_summary(stats, duration=time.time() - t0, store_name=store_name)

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

