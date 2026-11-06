"""Tests for the HTML→Markdown converter."""
from __future__ import annotations

from kbsync.convert import build_markdown, html_to_md, slug_from_url

# ---------------------------------------------------------------------------
# html_to_md tests
# ---------------------------------------------------------------------------

def test_iframe_becomes_link():
    html = '<iframe src="https://www.youtube.com/embed/abc" title="YouTube video"></iframe>'
    md = html_to_md(html)
    assert "[Embedded video: YouTube video](https://www.youtube.com/embed/abc)" in md


def test_iframe_without_title_uses_src():
    html = '<iframe src="https://www.youtube.com/embed/xyz"></iframe>'
    md = html_to_md(html)
    assert "Embedded video:" in md
    assert "https://www.youtube.com/embed/xyz" in md


def test_table_converts_to_gfm():
    html = (
        "<table><thead><tr><th>Col A</th><th>Col B</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    md = html_to_md(html)
    assert "| Col A |" in md
    assert "| 1 |" in md


def test_code_block_fenced():
    html = "<pre><code>print('hello')</code></pre>"
    md = html_to_md(html)
    assert "```" in md
    assert "print('hello')" in md


def test_script_removed():
    html = "<p>visible text</p><script>alert(1);</script>"
    md = html_to_md(html)
    assert "<script>" not in md
    assert "alert" not in md
    assert "visible text" in md


def test_style_removed():
    html = "<p>content</p><style>.foo { color: red; }</style>"
    md = html_to_md(html)
    assert "<style>" not in md
    assert ".foo" not in md


def test_relative_link_preserved():
    html = '<a href="/hc/en-us/articles/123">some link</a>'
    md = html_to_md(html)
    assert "/hc/en-us/articles/123" in md


def test_nested_list():
    html = "<ul><li>item1<ul><li>sub1</li></ul></li><li>item2</li></ul>"
    md = html_to_md(html)
    assert "item1" in md
    assert "sub1" in md
    assert "item2" in md


def test_nbsp_replaced_with_space():
    html = "<p>hello&nbsp;world</p>"
    md = html_to_md(html)
    assert "\u00a0" not in md
    assert "hello world" in md


def test_no_trailing_whitespace_on_lines():
    html = "<p>text with trailing space   </p>"
    md = html_to_md(html)
    for line in md.splitlines():
        assert line == line.rstrip(), f"Trailing whitespace found: {line!r}"


# ---------------------------------------------------------------------------
# slug_from_url tests
# ---------------------------------------------------------------------------

def test_slug_from_url():
    url = "https://support.optisigns.com/hc/en-us/articles/360021855653-What-hardware"
    assert slug_from_url(url) == "360021855653-What-hardware"


def test_slug_from_url_trailing_slash():
    url = "https://support.optisigns.com/hc/en-us/articles/360021855653-What-hardware/"
    assert slug_from_url(url) == "360021855653-What-hardware"


# ---------------------------------------------------------------------------
# build_markdown tests
# ---------------------------------------------------------------------------

def test_hash_stable_across_updated_at():
    """Hash must NOT change when only updated_at changes."""
    article1 = {
        "id": 1, "title": "Test", "body": "<p>hello</p>",
        "html_url": "https://x.com/hc/en-us/articles/1-test",
        "updated_at": "2024-01-01",
    }
    article2 = dict(article1, updated_at="2025-12-31")
    _, h1 = build_markdown(article1)
    _, h2 = build_markdown(article2)
    assert h1 == h2, "Hash must not include updated_at"


def test_hash_changes_on_body_change():
    """Hash must change when body content changes."""
    article1 = {
        "id": 1, "title": "Test", "body": "<p>original</p>",
        "html_url": "https://x.com/hc/en-us/articles/1-test",
        "updated_at": "2024-01-01",
    }
    article2 = dict(article1, body="<p>changed content</p>")
    _, h1 = build_markdown(article1)
    _, h2 = build_markdown(article2)
    assert h1 != h2


def test_build_markdown_has_header():
    article = {
        "id": 1, "title": "My Article", "body": "<p>Content here.</p>",
        "html_url": "https://x.com/hc/en-us/articles/1-my-article",
        "updated_at": "2024-01-01",
    }
    content, _ = build_markdown(article)
    assert content.startswith("# My Article")
    assert "Article URL: https://x.com/hc/en-us/articles/1-my-article" in content
    assert "Last updated: 2024-01-01" in content


def test_build_markdown_with_section():
    article = {
        "id": 1, "title": "My Article", "body": "<p>Content.</p>",
        "html_url": "https://x.com/hc/en-us/articles/1-my-article",
        "updated_at": "2024-01-01",
    }
    content, _ = build_markdown(article, section="Getting Started › Devices")
    assert "Section: Getting Started › Devices" in content


def test_build_markdown_hash_is_hex():
    article = {
        "id": 1, "title": "Test", "body": "<p>body</p>",
        "html_url": "https://x.com/1",
        "updated_at": "2024-01-01",
    }
    _, h = build_markdown(article)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
