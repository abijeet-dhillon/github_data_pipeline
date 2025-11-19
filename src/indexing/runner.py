"""Entry point wiring configuration, Elasticsearch client, and indexing logic."""

from __future__ import annotations

from typing import Optional, List

from .client import ESClient
from .config import IndexingSettings, parse_args, resolve_settings
from .indexer import scan_and_index


def _build_client(settings: IndexingSettings) -> ESClient:
    return ESClient(
        base_url=settings.es_url,
        username=settings.username,
        password=settings.password,
        api_key=settings.api_key,
        verify_tls=settings.verify_tls,
    )


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for indexing exported GitHub metadata."""

    args = parse_args(argv)
    settings = resolve_settings(args)
    client = _build_client(settings)
    scan_and_index(
        client,
        data_dir=settings.data_dir,
        index_prefix=settings.prefix,
        dry_run=settings.dry_run,
        batch_size=settings.batch_size,
    )


__all__ = ["main"]
