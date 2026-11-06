
#!/usr/bin/env python3
"""Check Gemini File Search Store status."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kbsync.config import Config
from kbsync.store import KnowledgeStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def main():
    print("[1] CHECK_STORE STARTED", flush=True)

    try:
        cfg = Config.from_env()
        print("[2] CONFIG LOADED", flush=True)

        store = KnowledgeStore(
            api_key=cfg.api_key,
            display_name=cfg.store_display_name,
            chunk_tokens=cfg.chunk_tokens,
            overlap=cfg.overlap,
        )

        print("[3] CONNECTING TO GEMINI...", flush=True)

        stores = list(store.client.file_search_stores.list())

        print(f"[4] FOUND {len(stores)} STORES", flush=True)

        store_resource = None

        for item in stores:
            print(
                f"    Store: {item.display_name} | {item.name}",
                flush=True,
            )

            if item.display_name == cfg.store_display_name:
                store_resource = item.name
                break

        if not store_resource:
            print("[ERROR] STORE NOT FOUND", flush=True)
            return 1

        print(f"[5] USING STORE: {store_resource}", flush=True)

        print("[6] FETCHING DOCUMENTS...", flush=True)

        documents = store.list_documents(store_resource)

        print(f"[7] DOCUMENTS RECEIVED: {len(documents)}", flush=True)

        parsed = []
        unparsed = []

        for doc in documents:
            state = store._parse_doc_state(doc)

            if state:
                parsed.append(state)
            else:
                unparsed.append(doc)

        from collections import Counter

        counts = Counter(item.article_id for item in parsed)

        duplicates = {
            article_id: count
            for article_id, count in counts.items()
            if count > 1
        }

        print("\n========== STORE SUMMARY ==========")
        print(f"Total documents: {len(documents)}")
        print(f"Parsed documents: {len(parsed)}")
        print(f"Unique articles: {len(counts)}")
        print(f"Unparsed documents: {len(unparsed)}")
        print(f"Duplicate article IDs: {len(duplicates)}")
        print("===================================")

        return 0

    except Exception:
        import traceback
        traceback.print_exc()
        return 1



if __name__ == "__main__":
    sys.exit(main())
