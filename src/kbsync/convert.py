"""HTML → Markdown converter for Zendesk Help Center articles.

Conversion rules (per spec):
- script/style/noscript/form/button → decompose (remove entirely)
- iframe → <a href=src>Embedded video: title</a>
- div/span → unwrap (keep content)
- empty <p> (no text, no img, no a) → decompose
- Keep only: href, src, alt, title attributes
- nbsp / zero-width spaces → clean up
- Heading style: ATX (## instead of underline)
- Relative links: preserved as-is (spec §7A row 7)
- Content hash: sha256(title.strip() + "\\n" + markdown_body) — does NOT include "Last updated:" line
"""
from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup
from markdownify import markdownify as _md

KEEP_ATTRS = {"href", "src", "alt", "title"}
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def clean_dom(html: str) -> BeautifulSoup:
    """Clean the HTML DOM before Markdown conversion."""
    # Wrap any stray embed code snippet (&lt;iframe...&gt;) in <pre><code> if not already in <pre>
    if "&lt;iframe" in (html or "") and not re.search(r"<pre[^>]*>\s*(?:<code>)?\s*&lt;iframe", html or ""):
        html = re.sub(r"&lt;iframe[\s\S]*?&lt;/iframe&gt;", lambda m: f"<pre><code>{m.group(0)}</code></pre>", html)

    soup = BeautifulSoup(html or "", "html.parser")

    # Demote any h1 in article body to h2 so the article title is the only H1 in the document
    for h1 in soup.find_all("h1"):
        h1.name = "h2"

    # Remove unwanted elements entirely
    for tag in soup(["script", "style", "noscript", "form", "button"]):
        tag.decompose()

    # Convert iframe → anchor link so the YouTube URL survives
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        title = iframe.get("title") or src
        a = soup.new_tag("a", href=src)
        a.string = f"Embedded video: {title}"
        iframe.replace_with(a)

    # Strip all attributes except the allowed set
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in KEEP_ATTRS}

    # Unwrap structural-only tags
    for tag in soup.find_all(["div", "span"]):
        tag.unwrap()

    # Remove empty paragraphs (no text, no images, no links)
    for p in soup.find_all("p"):
        if not p.get_text(strip=True) and not p.find(["img", "a"]):
            p.decompose()

    return soup


def html_to_md(html: str) -> str:
    """Convert HTML string to clean Markdown."""
    cleaned = str(clean_dom(html))
    text = _md(cleaned, heading_style="ATX", bullets="-")

    # Clean up whitespace artefacts
    text = text.replace("\u00a0", " ")          # non-breaking space → regular space
    text = _ZERO_WIDTH.sub("", text)             # remove zero-width characters
    text = _TRAILING_SPACES.sub("\n", text)      # strip trailing spaces on lines
    text = _MANY_BLANK_LINES.sub("\n\n", text)   # collapse 3+ blank lines to 2

    return text.strip() + "\n"


def build_markdown(
    article: dict,
    section: str | None = None,
) -> tuple[str, str]:
    """Build the final .md file content and compute the content hash.

    Returns:
        (file_content, content_hash)

    The content_hash is sha256(title.strip() + "\\n" + markdown_body).
    It deliberately excludes the "Last updated:" header line so that
    metadata-only changes (updated_at) do not trigger a re-upload.
    """
    title = (article.get("title") or "").strip()
    body_md = html_to_md(article.get("body") or "")

    # Build header block
    header_lines = [
        f"# {title}",
        "",
        f"Article URL: {article['html_url']}",
    ]
    if section:
        header_lines.append(f"Section: {section}")
    header_lines.append(f"Last updated: {article.get('updated_at', '')}")

    file_content = "\n".join(header_lines) + "\n\n" + body_md

    # Hash excludes "Last updated:" — hash only title + body
    content_hash = hashlib.sha256(
        (title + "\n" + body_md).encode("utf-8")
    ).hexdigest()

    return file_content, content_hash


def slug_from_url(html_url: str) -> str:
    """Extract the slug from the article's html_url.

    Example:
        "https://support.optisigns.com/hc/en-us/articles/360021855653-What-hardware"
        → "360021855653-What-hardware"
    """
    return html_url.rstrip("/").rsplit("/", 1)[-1]
