"""HTML → Markdown converter for Zendesk Help Center articles.

Conversion rules (per spec):
- script/style/noscript/form/button → decompose (remove entirely)
- iframe → <a href=src>Embedded video: title</a>
- <img>/<a> whose URL is an inline ``data:`` URI (base64 image) → short text
  placeholder. A single embedded screenshot can be >100 KB on one line; the
  Gemini File Search whitespace chunker cannot split it and the upload hangs
  until it times out (503), so these must never reach the .md file.
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
import logging
import re

from bs4 import BeautifulSoup
from markdownify import markdownify as _md

logger = logging.getLogger(__name__)

KEEP_ATTRS = {"href", "src", "alt", "title"}
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")

# Safety net applied to the final Markdown, in case a data: URI slips past the
# DOM step (e.g. it appears in plain text or inside a code block).
_MD_DATA_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*data:[^)]*\)", re.IGNORECASE)
_BARE_DATA_URI = re.compile(r"data:[\w.+-]+/[\w.+-]+;base64,[A-Za-z0-9+/=_-]{100,}", re.IGNORECASE)


def _is_data_uri(value: str | None) -> bool:
    return bool(value) and value.strip().lower().startswith("data:")


def _strip_inline_data_uris(soup: BeautifulSoup) -> int:
    """Replace <img>/<a> pointing at a ``data:`` URI with a short text placeholder.

    Returns the number of elements replaced.
    """
    removed = 0

    for img in soup.find_all("img"):
        if _is_data_uri(img.get("src")):
            alt = (img.get("alt") or "").strip()
            img.replace_with(f"[Inline image: {alt}]" if alt else "[Inline image]")
            removed += 1

    for a in soup.find_all("a"):
        if _is_data_uri(a.get("href")):
            # keep the visible link text, drop the huge URL
            a.unwrap()
            removed += 1

    return removed


def clean_dom(html: str, context: str = "") -> BeautifulSoup:
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

    # Replace inline base64 images/links BEFORE attributes are stripped (src/href are kept below)
    n_data = _strip_inline_data_uris(soup)
    if n_data:
        logger.info("Stripped %d inline data: URI(s)%s", n_data, f" in {context}" if context else "")

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


def html_to_md(html: str, context: str = "") -> str:
    """Convert HTML string to clean Markdown."""
    cleaned = str(clean_dom(html, context))
    text = _md(cleaned, heading_style="ATX", bullets="-")

    # Safety net: no base64 payload may survive into the Markdown
    text = _MD_DATA_IMAGE.sub(lambda m: f"[Inline image: {m.group(1).strip()}]" if m.group(1).strip() else "[Inline image]", text)
    text = _BARE_DATA_URI.sub("[inline data removed]", text)

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
    body_md = html_to_md(article.get("body") or "", context=slug_from_url(article.get("html_url") or ""))

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