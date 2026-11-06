#!/usr/bin/env python3
"""scripts/upload.py — Task 2 CLI: full-load upload of Markdown files to Gemini File Search store.

Usage:
    python scripts/upload.py [--dir data/articles] [--store optibot-support-kb] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kbsync.config import Config
from kbsync.logging_setup import setup_logging
from kbsync.store import KnowledgeStore, estimate_chunks

logger = logging.getLogger(__name__)

_MAX_UPLOAD_RETRIES = 3


def upload_with_retry(
    store: KnowledgeStore,
    store_name: str,
    path: Path,
    slug: str,
    meta: dict,
    dry_run: bool,
) -> tuple[bool, int]:
    """Upload a file with retry. Returns (success, estimated_chunks)."""
    content = path.read_text(encoding="utf-8")
    n_tokens = len(content.split())
    chunks = estimate_chunks(n_tokens, store.chunk_tokens, store.overlap)

    if dry_run:
        logger.info("[DRY-RUN] Would upload: %s (~%d chunks)", path.name, chunks)
        return True, chunks

    for attempt in range(_MAX_UPLOAD_RETRIES):
        try:
            store.upload(store_name, str(path), slug, meta)
            return True, chunks
        except Exception as exc:  # pylint: disable=broad-except
            wait = 2 ** attempt + (attempt * 0.5)  # backoff + jitter
            logger.warning(
                "Upload failed for %s (attempt %d/%d): %s. Retrying in %.1fs...",
                path.name, attempt + 1, _MAX_UPLOAD_RETRIES, exc, wait
            )
            if attempt < _MAX_UPLOAD_RETRIES - 1:
                time.sleep(wait)

    logger.error("Upload permanently failed for: %s", path.name)
    return False, 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Upload Markdown articles to Gemini File Search store.")
    p.add_argument("--dir", default="data/articles", help="Directory of .md files")
    p.add_argument("--store", default=None, help="Store display name (overrides env)")
    p.add_argument("--dry-run", action="store_true", help="Print plan without calling API")
    p.add_argument("--workers", type=int, default=None, help="Max concurrent uploads")
    return p.parse_args()


def main() -> int:
    setup_logging()
    args = parse_args()

    cfg = Config.from_env()
    store_name_override = args.store or cfg.store_display_name
    max_workers = args.workers or cfg.max_workers
    dry_run = args.dry_run or cfg.dry_run

    articles_dir = Path(args.dir)
    if not articles_dir.exists():
        logger.error("Articles directory not found: %s", articles_dir)
        return 1

    md_files = sorted(articles_dir.glob("*.md"))
    if not md_files:
        logger.warning("No .md files found in %s", articles_dir)
        return 0

    # Try to load manifest for metadata
    manifest_path = articles_dir.parent / "manifest.json"
    manifest_by_slug: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_by_slug = {e["slug"]: e for e in manifest}
            logger.info("Loaded manifest with %d entries.", len(manifest_by_slug))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not load manifest: %s", exc)

    store = KnowledgeStore(
        api_key=cfg.api_key,
        display_name=store_name_override,
        chunk_tokens=cfg.chunk_tokens,
        overlap=cfg.overlap,
    )

    if not dry_run:
        store_resource = store.get_or_create_store()
        logger.info("Using store: %s", store_resource)
    else:
        store_resource = f"[DRY-RUN] {store_name_override}"
        logger.info("[DRY-RUN] Would use store: %s", store_name_override)

    files_uploaded = 0
    files_failed = 0
    total_chunks = 0

    def _task(path: Path) -> tuple[bool, int]:
        slug = path.stem  # filename without .md
        # Remove __hash8 suffix if present (Plan B naming)
        base_slug = slug.split("__")[0] if "__" in slug else slug
        entry = manifest_by_slug.get(base_slug, {})
        meta = {
            "id": entry.get("id", base_slug.split("-")[0]),
            "hash": entry.get("content_hash", ""),
            "url": entry.get("url", ""),
            "updated_at": entry.get("updated_at", ""),
        }
        return upload_with_retry(store, store_resource, path, base_slug, meta, dry_run)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_task, p): p for p in md_files}
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                success, chunks = fut.result()
                if success:
                    files_uploaded += 1
                    total_chunks += chunks
                else:
                    files_failed += 1
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Unexpected error uploading %s: %s", path.name, exc)
                files_failed += 1

    summary = {
        "event": "upload_summary",
        "files_uploaded": files_uploaded,
        "chunks_estimated": total_chunks,
        "failed": files_failed,
        "chunk_cfg": {"max": cfg.chunk_tokens, "overlap": cfg.overlap},
        "store": store_resource,
        "dry_run": dry_run,
    }
    print(json.dumps(summary), flush=True)

    return 0 if files_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

