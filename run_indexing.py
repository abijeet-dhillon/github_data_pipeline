"""Compatibility wrapper for the modular indexing package."""

from __future__ import annotations
import sys
from typing import List, Optional
from src.indexing.runner import main as run_indexer


def main(argv: Optional[List[str]] = None) -> None:
    """Delegate execution to `src.indexing.runner.main`."""
    run_indexer(argv)


if __name__ == "__main__":
    main()
