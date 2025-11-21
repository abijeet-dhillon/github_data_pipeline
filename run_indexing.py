"""Convenience shim to run only the indexing workflow."""

from __future__ import annotations

import sys

from src.indexing.runner import main as indexing_main


if __name__ == "__main__":
    indexing_main(sys.argv[1:])
