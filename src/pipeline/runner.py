"""Pipeline runner that ensures retrieval completes before indexing."""

from __future__ import annotations

import sys
from typing import List, Optional

from src.retrieval import runner as retrieval_runner
from src.indexing import runner as indexing_runner


def main(repos: Optional[List[str]] = None,
         indexing_args: Optional[List[str]] = None) -> None:
    """Execute retrieval first, then index the produced artifacts."""

    retrieval_runner.main(repos)
    indexing_runner.main(indexing_args)


if __name__ == "__main__":
    repo_args = [arg for arg in sys.argv[1:] if "/" in arg] if len(sys.argv) > 1 else None
    main(repo_args)
