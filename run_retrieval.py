"""Convenience shim to run only the retrieval workflow."""

from __future__ import annotations

import sys

from src.retrieval.runner import main as retrieval_main


if __name__ == "__main__":
    args = sys.argv[1:]
    repos = [arg for arg in args if "/" in arg] if args else None
    retrieval_main(repos)
