"""Tests for ZendeskClient — cursor pagination, retry, and fallback offset.

All sleep calls are patched out so tests run instantly.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from kbsync.zendesk import ZendeskClient

BASE = "https://support.optisigns.com"
ARTICLES_PATH = "/api/v2/help_center/en-us/articles.json"


@respx.mock
def test_cursor_pagination_fetches_all_pages():
    """Two pages with cursor pagination should yield 2 articles."""
    page1 = {
        "articles": [{"id": 1}],
        "meta": {"has_more": True},
        "links": {"next": f"{BASE}{ARTICLES_PATH}?page[after]=cur123"},
    }
    page2 = {
        "articles": [{"id": 2}],
        "meta": {"has_more": False},
        "links": {},
    }
    respx.get(path=ARTICLES_PATH).side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ]

    articles = list(ZendeskClient(BASE).iter_articles())
    assert [a["id"] for a in articles] == [1, 2]


@respx.mock
def test_cursor_stops_when_has_more_false():
    """has_more=False → stop, even if links.next is populated."""
    page1 = {
        "articles": [{"id": 10}],
        "meta": {"has_more": False},
        "links": {"next": f"{BASE}{ARTICLES_PATH}?page[after]=cur123"},
    }
    respx.get(path=ARTICLES_PATH).mock(return_value=httpx.Response(200, json=page1))

    articles = list(ZendeskClient(BASE).iter_articles())
    assert len(articles) == 1
    assert articles[0]["id"] == 10


@respx.mock
@patch("kbsync.zendesk.time.sleep")
def test_retries_on_429(mock_sleep):
    """Should retry on 429 (Retry-After header respected) and succeed."""
    respx.get(path=ARTICLES_PATH).side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"articles": [{"id": 99}], "meta": {"has_more": False}, "links": {}}),
    ]
    articles = list(ZendeskClient(BASE).iter_articles())
    assert len(articles) == 1
    assert articles[0]["id"] == 99
    mock_sleep.assert_called()


@respx.mock
@patch("kbsync.zendesk.time.sleep")
def test_retries_on_500(mock_sleep):
    """Should retry on 5xx and succeed on the second attempt."""
    respx.get(path=ARTICLES_PATH).side_effect = [
        httpx.Response(500),
        httpx.Response(200, json={"articles": [{"id": 42}], "meta": {"has_more": False}, "links": {}}),
    ]
    articles = list(ZendeskClient(BASE).iter_articles())
    assert len(articles) == 1
    assert articles[0]["id"] == 42
    mock_sleep.assert_called()


@respx.mock
def test_fallback_offset_pagination():
    """Should fall back to next_page when links is absent."""
    page1 = {
        "articles": [{"id": 10}],
        "next_page": f"{BASE}{ARTICLES_PATH}?page=2",
    }
    page2 = {
        "articles": [{"id": 20}],
        "next_page": None,
    }
    respx.get(path=ARTICLES_PATH).side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ]

    articles = list(ZendeskClient(BASE).iter_articles())
    assert [a["id"] for a in articles] == [10, 20]


@respx.mock
@patch("kbsync.zendesk.time.sleep")
def test_raises_after_max_retries(mock_sleep):
    """Should raise RuntimeError after all retries are exhausted."""
    respx.get(path=ARTICLES_PATH).mock(return_value=httpx.Response(503))
    with pytest.raises(RuntimeError, match="failed after"):
        list(ZendeskClient(BASE).iter_articles())
