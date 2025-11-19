"""Legacy compatibility wrapper that delegates to the retrieval package."""

from __future__ import annotations

import sys
from typing import List, Optional

from src.retrieval.runner import main as run_retrieval


def main(custom_repos: Optional[List[str]] = None) -> None:
    """Delegate to the modular retrieval runner (formerly pipeline)."""

    run_retrieval(custom_repos)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        repos = [arg for arg in sys.argv[1:] if "/" in arg]
    else:
        repos = None
    main(repos)
