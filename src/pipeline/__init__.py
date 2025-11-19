"""GitHub data pipeline package with modular components."""

from .runner import main, process_repo

__all__ = ["main", "process_repo"]
