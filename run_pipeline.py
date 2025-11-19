"""Compatibility wrapper around the modular pipeline package."""

from __future__ import annotations
import sys
from typing import List, Optional
from src.pipeline.runner import main as run_pipeline


def main(custom_repos: Optional[List[str]] = None) -> None:
    """Delegate to the modular pipeline runner."""
    run_pipeline(custom_repos)


if __name__ == "__main__":
        main()
