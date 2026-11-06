#!/usr/bin/env python3
"""scripts/validate_md.py — Validate quality of scraped Markdown files.

Usage:
    python scripts/validate_md.py [directory] [--dir data/articles]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_HTML_TAG_RE = re.compile(r"<(div|span|table|iframe|script|style)", re.IGNORECASE)
_STYLE_ATTR_RE = re.compile(r'\bstyle\s*=\s*["\']', re.IGNORECASE)
_H1_LINE_RE = re.compile(r"^# .+", re.MULTILINE)
_ARTICLE_URL_RE = re.compile(r"^Article URL:", re.MULTILINE)
_NBSP_RE = re.compile(r"\u00a0")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_FENCE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def validate_file(path: Path) -> list[str]:
    """Return list of error strings for the file, or empty list if OK."""
    errors: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"Cannot read file: {exc}"]

    # Strip code blocks and inline code before checking prose for raw HTML tags
    prose = _FENCE_BLOCK_RE.sub("", content)
    prose = _INLINE_CODE_RE.sub("", prose)

    # 1. No raw HTML tags in prose
    m = _HTML_TAG_RE.search(prose)
    if m:
        errors.append(f"Raw HTML tag found: {m.group()!r}")

    # 2. No style= attributes in prose
    if _STYLE_ATTR_RE.search(prose):
        errors.append("style= attribute found")

    # 3. Balanced code fences
    fence_count = content.count("```")
    if fence_count % 2 != 0:
        errors.append(f"Unbalanced code fences: {fence_count} occurrences")

    # 4. Exactly one H1 at start
    h1_matches = _H1_LINE_RE.findall(content)
    if len(h1_matches) != 1 or not content.startswith("# "):
        errors.append(f"Expected exactly 1 H1 at start, found {len(h1_matches)}")

    # 5. Has Article URL line
    if not _ARTICLE_URL_RE.search(content):
        errors.append("Missing 'Article URL:' line")

    # 6. Body length ≥ 100 chars
    if len(content.strip()) < 100:
        errors.append(f"Content too short: {len(content.strip())} chars")

    # 7. No &nbsp; or zero-width chars
    if _NBSP_RE.search(content):
        errors.append("Non-breaking space (\\u00a0) found")
    if _ZERO_WIDTH_RE.search(content):
        errors.append("Zero-width character found")

    return errors


def main() -> int:
    p = argparse.ArgumentParser(description="Validate quality of .md articles.")
    p.add_argument("directory", nargs="?", default="data/articles", help="Directory of .md files")
    p.add_argument("--dir", default=None, help="Alternative way to specify directory")
    args = p.parse_args()

    directory = Path(args.dir or args.directory)
    if not directory.exists():
        print(f"ERROR: Directory not found: {directory}", file=sys.stderr)
        return 1

    md_files = sorted(directory.glob("*.md"))
    if not md_files:
        print(f"WARNING: No .md files found in {directory}")
        return 0

    # Check for duplicate slugs
    slugs = [f.stem for f in md_files]
    seen: set[str] = set()
    duplicate_errors: list[str] = []
    for slug in slugs:
        if slug in seen:
            duplicate_errors.append(f"Duplicate slug: {slug}")
        seen.add(slug)

    total_errors = 0
    for path in md_files:
        file_errors = validate_file(path)
        if file_errors:
            total_errors += len(file_errors)
            for err in file_errors:
                print(f"  FAIL [{path.name}]: {err}")

    for err in duplicate_errors:
        total_errors += 1
        print(f"  FAIL: {err}")

    if total_errors == 0:
        print(f"OK: {len(md_files)} files, 0 errors")
        return 0
    else:
        print(f"\nFAIL: {len(md_files)} files, {total_errors} error(s)")
        return 1


if __name__ == "__main__":
    sys.exit(main())

