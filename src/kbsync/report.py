"""Run summary reporting."""
from __future__ import annotations

import json
import logging

from kbsync.models import RunStats

logger = logging.getLogger(__name__)


def emit_summary(stats: RunStats, duration: float, store_name: str = "") -> None:
    """Print a JSON summary line to stdout and log it."""
    summary = {
        "event": "run_summary",
        "fetched": stats.fetched,
        "skipped_draft": stats.skipped_draft,
        "skipped_empty": stats.skipped_empty,
        "added": stats.added,
        "updated": stats.updated,
        "skipped": stats.skipped,
        "deleted": stats.deleted,
        "failed": stats.failed,
        "chunks_estimated": stats.chunks_estimated,
        "duration_s": round(duration, 1),
        "store": store_name,
    }
    line = json.dumps(summary)
    print(line, flush=True)
    logger.info("Run complete: %s", line)

