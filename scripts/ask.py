#!/usr/bin/env python3
"""scripts/ask.py — Query the OptiBot assistant and print the answer with citations.

Usage:
    python scripts/ask.py "How do I add a YouTube video?" [--store optibot-support-kb]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kbsync.config import Config
from kbsync.logging_setup import setup_logging
from kbsync.store import KnowledgeStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Query OptiBot via Gemini File Search.")
    p.add_argument("question", help="The question to ask OptiBot")
    p.add_argument("--store", default=None, help="Store display name (overrides env)")
    p.add_argument("--model", default=None, help="Gemini model name (overrides env)")
    return p.parse_args()


def main() -> int:
    setup_logging(level="WARNING")  # Keep output clean for demos
    args = parse_args()

    cfg = Config.from_env()
    model = args.model or cfg.gemini_model
    store_display_name = args.store or cfg.store_display_name

    # Read system prompt (verbatim per spec)
    if not SYSTEM_PROMPT_PATH.exists():
        print(f"ERROR: System prompt not found at {SYSTEM_PROMPT_PATH}", file=sys.stderr)
        return 1
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()

    # Find the store
    knowledge_store = KnowledgeStore(cfg.api_key, store_display_name)
    store_name: str | None = None
    try:
        client = knowledge_store.client
        for s in client.file_search_stores.list():
            if s.display_name == store_display_name:
                store_name = s.name
                break
    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: Could not connect to Gemini API: {exc}", file=sys.stderr)
        return 1

    if not store_name:
        print(f"ERROR: Store '{store_display_name}' not found. Run upload.py first.", file=sys.stderr)
        return 1

    logger.info("Using store: %s, model: %s", store_name, model)

    # Query the assistant
    try:
        from google import genai  # noqa: F811
        client = genai.Client(api_key=cfg.api_key)

        # Try the interactions API (verify exact method with installed SDK)
        try:
            interaction = client.models.generate_content(
                model=model,
                contents=args.question,
                config={
                    "system_instruction": system_prompt,
                    "tools": [{"file_search": {"file_search_store_names": [store_name]}}],
                },
            )
            # Extract text and annotations
            for candidate in (interaction.candidates or []):
                for part in (candidate.content.parts or []):
                    if hasattr(part, "text") and part.text:
                        print(part.text)
                    # Print citations
                    for ann in (getattr(part, "annotations", None) or []):
                        if getattr(ann, "type", "") == "file_citation":
                            meta = getattr(ann, "custom_metadata", None) or {}
                            url = (meta.get("url") if isinstance(meta, dict) else None) or getattr(ann, "source", "")
                            if url:
                                print(f"Article URL: {url}")

        except AttributeError:
            # Fallback: try interactions.create API
            interaction = client.interactions.create(
                model=model,
                input=args.question,
                system_instruction=system_prompt,
                tools=[{"type": "file_search", "file_search_store_names": [store_name]}],
            )
            for step in (interaction.steps or []):
                if getattr(step, "type", "") == "model_output":
                    for block in (step.content or []):
                        if getattr(block, "type", "") == "text":
                            print(block.text)
                            for ann in (block.annotations or []):
                                if getattr(ann, "type", "") == "file_citation":
                                    meta = getattr(ann, "custom_metadata", None) or {}
                                    url = (meta.get("url") if isinstance(meta, dict) else None) or getattr(ann, "source", "")
                                    if url:
                                        print(f"Article URL: {url}")

    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: Query failed: {exc}", file=sys.stderr)
        logger.exception("Query error")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

