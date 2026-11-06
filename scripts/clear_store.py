
#!/usr/bin/env python3
"""Delete all documents from an existing Gemini File Search Store.

Default: Dry run (only list documents).
Use --yes to actually delete.
"""

import argparse
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
    parser = argparse.ArgumentParser(
        description="Clear documents from Gemini File Search Store"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete all documents",
    )
    args = parser.parse_args()

    cfg = Config.from_env()

    store = KnowledgeStore(
        api_key=cfg.api_key,
        display_name=cfg.store_display_name,
        chunk_tokens=cfg.chunk_tokens,
        overlap=cfg.overlap,
    )

    # Find existing store
    store_resource = None

    for item in store.client.file_search_stores.list():
        if item.display_name == cfg.store_display_name:
            store_resource = item.name
            break

    if not store_resource:
        print("ERROR: Store not found!")
        return 1

    print("\nSTORE:", store_resource)

    # List documents
    documents = store.list_documents(store_resource)

    print(f"\nFound {len(documents)} documents.")

    if not documents:
        print("Store is already empty.")
        return 0

    # Preview
    print("\nDocuments to delete:")

    for index, doc in enumerate(documents, 1):
        print(
            f"{index}. "
            f"{getattr(doc, 'display_name', 'unknown')} "
            f"| {doc.name}"
        )

    if not args.yes:
        print("\nDRY RUN: No documents were deleted.")
        print("Run with --yes to confirm deletion.")
        return 0

    # Delete confirmation
    confirm = input(
        f"\nWARNING: Delete ALL {len(documents)} documents? "
        "Type DELETE to continue: "
    )

    if confirm != "DELETE":
        print("Cancelled. Nothing deleted.")
        return 0

    # Delete documents
    deleted = 0
    failed = 0

    for index, doc in enumerate(documents, 1):
        try:
            print(
                f"[{index}/{len(documents)}] "
                f"Deleting {getattr(doc, 'display_name', doc.name)}..."
            )

            store.delete_document(doc.name)
            deleted += 1

        except Exception:
            failed += 1
            logging.exception(
                "Failed to delete document: %s",
                doc.name,
            )

    print("\n========== DELETE SUMMARY ==========")
    print(f"Total documents: {len(documents)}")
    print(f"Deleted:         {deleted}")
    print(f"Failed:          {failed}")
    print("====================================")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
