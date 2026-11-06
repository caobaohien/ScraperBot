#!/usr/bin/env python3
"""scripts/scrape.py — Task 1 CLI: scrape Zendesk Help Center → Markdown files.

Usage:
    python scripts/scrape.py [--out data/articles] [--limit 0] [--save-raw] [--locale en-us]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow running from repo root without installing package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kbsync.config import Config
from kbsync.convert import build_markdown, slug_from_url
from kbsync.logging_setup import setup_logging
from kbsync.zendesk import ZendeskClient

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Zendesk Help Center articles to Markdown.")
    p.add_argument("--out", default="data/articles", help="Output directory for .md files")
    p.add_argument("--limit", type=int, default=0, help="Max articles (0 = all)")
    p.add_argument("--save-raw", action="store_true", help="Save raw JSON to data/raw/articles.json")
    p.add_argument("--locale", default=None, help="Locale (overrides env ZENDESK_LOCALE)")
    p.add_argument("--base-url", default=None, help="Zendesk base URL (overrides env)")
    return p.parse_args()


def main() -> int:
    setup_logging()
    args = parse_args()

    cfg = Config.from_env()
    if args.locale:
        cfg.locale = args.locale
    if args.base_url:
        cfg.zendesk_base_url = args.base_url
    limit = args.limit or cfg.limit

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = ZendeskClient(cfg.zendesk_base_url, cfg.locale)

    # Optionally fetch sections for enrichment
    sections: dict[int, str] = {}
    try:
        sections = client.get_sections()
        logger.info("Loaded %d sections.", len(sections))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Could not load sections (continuing without): %s", exc)

    articles_raw: list[dict] = []
    written = 0
    skipped_draft = 0
    skipped_empty = 0
    manifest: list[dict] = []

    for article in client.iter_articles():
        if article.get("draft"):
            skipped_draft += 1
            logger.debug("Skipping draft: %s", article.get("id"))
            continue

        body = (article.get("body") or "").strip()
        # Strip HTML tags for length check
        from bs4 import BeautifulSoup
        plain = BeautifulSoup(body, "html.parser").get_text(strip=True)
        if len(plain) < 50:
            skipped_empty += 1
            logger.debug("Skipping too-short article: %s (len=%d)", article.get("id"), len(plain))
            continue

        section_label = sections.get(article.get("section_id", 0))
        content, content_hash = build_markdown(article, section=section_label)
        slug = slug_from_url(article["html_url"])
        file_path = out_dir / f"{slug}.md"

        file_path.write_text(content, encoding="utf-8")
        written += 1

        approx_tokens = len(content.split())
        manifest.append({
            "id": article["id"],
            "slug": slug,
            "url": article["html_url"],
            "title": article["title"],
            "updated_at": article.get("updated_at", ""),
            "content_hash": content_hash,
            "bytes": len(content.encode()),
            "approx_tokens": approx_tokens,
        })

        articles_raw.append(article)

        if limit and written >= limit:
            logger.info("Article limit %d reached.", limit)
            break

    # Write manifest
    manifest_path = out_dir.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Optionally save raw
    if args.save_raw:
        raw_dir = out_dir.parent / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "articles.json").write_text(
            json.dumps(articles_raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Raw JSON saved to %s", raw_dir / "articles.json")

    total_bytes = sum(e["bytes"] for e in manifest)
    print(
        f"Fetched: {len(articles_raw) + skipped_draft + skipped_empty} | "
        f"Skipped: {skipped_draft + skipped_empty} (draft={skipped_draft}, empty={skipped_empty}) | "
        f"Written: {written} | "
        f"Total: {total_bytes / 1024:.1f} KB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

