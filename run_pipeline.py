"""Legacy compatibility wrapper that runs retrieval + indexing pipeline."""

from __future__ import annotations

import sys
from typing import List, Optional

from src.pipeline.runner import main as run_pipeline


def main(custom_repos: Optional[List[str]] = None) -> None:
    """Delegate to the orchestrated pipeline runner."""

    run_pipeline(custom_repos)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        repos = [arg for arg in sys.argv[1:] if "/" in arg]
    else:
        repos = None
    main(repos)
