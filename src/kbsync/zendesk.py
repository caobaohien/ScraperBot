"""Zendesk Help Center API client with cursor pagination and retry."""
from __future__ import annotations

import logging
import time
from typing import Iterator

import httpx

logger = logging.getLogger(__name__)

UA = "kb-sync/1.0 (+support-doc-indexer)"
_MAX_RETRIES = 6


class ZendeskClient:
    """Fetches articles from the Zendesk Help Center API.

    Supports cursor pagination (page[size] + links.next) with fallback to
    offset pagination (next_page). Retries on 429 (rate-limited) and 5xx
    with exponential backoff.

    Note: Does NOT use httpx base_url so that absolute URLs from links.next
    are sent verbatim (no base_url merging). The base_url is stored
    separately and used only to build the initial request path.
    """

    def __init__(
        self,
        base_url: str,
        locale: str = "en-us",
        page_size: int = 100,
        timeout: float = 30.0,
    ) -> None:
        # Normalise — no trailing slash
        self.base_url = base_url.rstrip("/")
        self.locale = locale
        self.page_size = page_size
        # No base_url on the client: absolute URLs from links.next work correctly
        self.http = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": UA, "Accept": "application/json"},
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET with exponential backoff on 429 / 5xx.

        Accepts both absolute URLs (returned by links.next) and relative paths
        (which are resolved against self.base_url).
        """
        # Resolve relative paths
        if url.startswith("/"):
            url = self.base_url + url

        for attempt in range(_MAX_RETRIES):
            try:
                r = self.http.get(url, params=params)
            except httpx.TransportError as exc:
                wait = 2 ** attempt
                logger.warning(
                    "Transport error on attempt %d: %s — retrying in %ds", attempt, exc, wait
                )
                time.sleep(wait)
                continue

            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 2 ** attempt))
                logger.warning(
                    "Rate-limited (429). Waiting %ds (attempt %d).", retry_after, attempt
                )
                time.sleep(retry_after)
                continue

            if r.status_code >= 500:
                wait = 2 ** attempt
                logger.warning(
                    "Server error %d on attempt %d. Retrying in %ds.",
                    r.status_code, attempt, wait,
                )
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r.json()

        raise RuntimeError(f"GET {url!r} failed after {_MAX_RETRIES} retries")

    def iter_articles(self) -> Iterator[dict]:
        """Yield all published articles for the configured locale.

        Uses cursor pagination (page[size] + links.next) when available,
        falls back to offset pagination (next_page) for older Zendesk instances.
        """
        url: str | None = f"/api/v2/help_center/{self.locale}/articles.json"
        params: dict | None = {"page[size]": self.page_size}
        page_count = 0

        while url:
            data = self._get(url, params)
            articles = data.get("articles", [])
            yield from articles
            page_count += 1
            # After the first request the next URL is fully self-contained.
            params = None

            meta = data.get("meta", {})
            links = data.get("links", {})

            if links:
                # Cursor pagination: follow links.next only while has_more is True
                if meta.get("has_more"):
                    url = links.get("next")
                else:
                    url = None
            else:
                # Offset pagination fallback
                url = data.get("next_page")

        logger.info("Fetched articles across %d page(s).", page_count)

    def get_sections(self) -> dict[int, str]:
        """Return mapping of section_id -> 'Category › Section' label (optional enrichment)."""
        cat_data = self._get(f"/api/v2/help_center/{self.locale}/categories.json")
        categories: dict[int, str] = {
            c["id"]: c["name"] for c in cat_data.get("categories", [])
        }

        sections: dict[int, str] = {}
        url: str | None = f"/api/v2/help_center/{self.locale}/sections.json"
        params: dict | None = {"page[size]": 100}
        while url:
            data = self._get(url, params)
            for s in data.get("sections", []):
                cat_name = categories.get(s.get("category_id"), "")
                sections[s["id"]] = f"{cat_name} › {s['name']}" if cat_name else s["name"]
            params = None
            meta = data.get("meta", {})
            links = data.get("links", {})
            if links:
                url = links.get("next") if meta.get("has_more") else None
            else:
                url = data.get("next_page")

        return sections

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "ZendeskClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
