"""Logging configuration."""
from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger to output to stdout with a readable format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
