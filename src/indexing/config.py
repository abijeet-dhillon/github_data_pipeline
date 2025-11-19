"""Configuration helpers for the Elasticsearch indexing workflow."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.secrets import load_local_secrets

_SECRETS = load_local_secrets()
_ES_SECRETS = _SECRETS.get("elasticsearch", {})

HARDLOCK = True
HARDCODED_DATA_DIR = "./output"
HARDCODED_ES_URL = _ES_SECRETS.get("url", "http://localhost:9200")
HARDCODED_ES_USERNAME: Optional[str] = _ES_SECRETS.get("username")
HARDCODED_ES_PASSWORD: Optional[str] = _ES_SECRETS.get("password")
HARDCODED_ES_API_KEY = _ES_SECRETS.get("api_key", "")
HARDCODED_VERIFY_TLS = bool(_ES_SECRETS.get("verify_tls", False))
HARDCODED_INDEX_PREFIX = _ES_SECRETS.get("index_prefix", "")
HARDCODED_BATCH_SIZE = int(_ES_SECRETS.get("batch_size", 500))


@dataclass(frozen=True)
class IndexingSettings:
    """Resolved runtime settings for the indexing workflow."""

    data_dir: Path
    es_url: str
    username: Optional[str]
    password: Optional[str]
    api_key: Optional[str]
    verify_tls: bool
    prefix: str
    batch_size: int
    dry_run: bool


def build_arg_parser() -> argparse.ArgumentParser:
    """Return the CLI parser used by the indexing entry point."""

    parser = argparse.ArgumentParser(
        description="Index exported GitHub data into Elasticsearch with explicit mappings.",
    )
    parser.add_argument("--data-dir", default=HARDCODED_DATA_DIR)
    parser.add_argument("--es-url", default=HARDCODED_ES_URL)
    parser.add_argument("--username", default=HARDCODED_ES_USERNAME)
    parser.add_argument("--password", default=HARDCODED_ES_PASSWORD)
    parser.add_argument("--api-key", default=HARDCODED_ES_API_KEY)
    parser.add_argument("--verify-tls", action="store_true", default=HARDCODED_VERIFY_TLS)
    parser.add_argument("--prefix", default=HARDCODED_INDEX_PREFIX)
    parser.add_argument("--batch-size", type=int, default=HARDCODED_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments; accepts argv overrides for testing."""

    parser = build_arg_parser()
    return parser.parse_args(argv)


def _hardcoded_settings() -> IndexingSettings:
    return IndexingSettings(
        data_dir=Path(HARDCODED_DATA_DIR),
        es_url=HARDCODED_ES_URL,
        username=HARDCODED_ES_USERNAME,
        password=HARDCODED_ES_PASSWORD,
        api_key=HARDCODED_ES_API_KEY,
        verify_tls=HARDCODED_VERIFY_TLS,
        prefix=HARDCODED_INDEX_PREFIX,
        batch_size=HARDCODED_BATCH_SIZE,
        dry_run=False,
    )


def resolve_settings(args: Optional[argparse.Namespace] = None) -> IndexingSettings:
    """Return immutable settings, honoring HARDLOCK when enabled."""

    if HARDLOCK:
        return _hardcoded_settings()

    args = args or parse_args()
    return IndexingSettings(
        data_dir=Path(args.data_dir),
        es_url=args.es_url,
        username=args.username,
        password=args.password,
        api_key=args.api_key,
        verify_tls=bool(args.verify_tls),
        prefix=args.prefix,
        batch_size=int(args.batch_size),
        dry_run=bool(args.dry_run),
    )


__all__ = [
    "HARDLOCK",
    "HARDCODED_DATA_DIR",
    "HARDCODED_ES_URL",
    "HARDCODED_ES_USERNAME",
    "HARDCODED_ES_PASSWORD",
    "HARDCODED_ES_API_KEY",
    "HARDCODED_VERIFY_TLS",
    "HARDCODED_INDEX_PREFIX",
    "HARDCODED_BATCH_SIZE",
    "IndexingSettings",
    "build_arg_parser",
    "parse_args",
    "resolve_settings",
]
