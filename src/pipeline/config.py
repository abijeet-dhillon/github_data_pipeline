"""Central configuration constants for the GitHub data pipeline."""

from __future__ import annotations

import os
from typing import List

from src.secrets import load_local_secrets

_SECRETS = load_local_secrets()
GITHUB_TOKENS: List[str] = list(_SECRETS.get("github_tokens", []))
USER_AGENT = "cosc448-github-data-retrieval/1.0"
BASE_URL = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
PER_PAGE = 100
REQUEST_TIMEOUT = 90
MAX_RETRIES = max(6, len(GITHUB_TOKENS) * 2)
BACKOFF_BASE_SEC = 2
OUTPUT_DIR = "./output"
MAX_PAGES_COMMITS = int(os.getenv("MAX_PAGES_COMMITS", "0"))  # 0 = no cap
MAX_WAIT_ON_403 = int(os.getenv("MAX_WAIT_ON_403", "180"))
RATE_LIMIT_TOKEN_RESET_WAIT_SEC = int(
    os.getenv("RATE_LIMIT_TOKEN_RESET_WAIT_SEC", str(60 * 60))
)
INCREMENTAL_LOOKBACK_SEC = int(os.getenv("INCREMENTAL_LOOKBACK_SEC", "300"))
BLAME_EXAMPLE_LIMIT = int(os.getenv("BLAME_EXAMPLE_LIMIT", "5"))
BLAME_FILE_LIMIT = int(os.getenv("BLAME_FILE_LIMIT", "0"))

REPOS = [
    # "carsondrobe/fellas"
    "micromatch/micromatch"
    # "laravel-mix/laravel-mix",
    # "standard/standard",
    # "istanbuljs/nyc",
    # "axios/axios",
    # "rollup/rollup",
    # "flutter/flutter",
    # "apache/spark",
    # "reduxjs/redux",
    # "torvalds/linux",
    # "grafana/grafana",
    # "django/django",
    # "prettier/prettier",
    # "numpy/numpy",
    # "pandas-dev/pandas"   
]

__all__ = [
    "GITHUB_TOKENS",
    "USER_AGENT",
    "BASE_URL",
    "GRAPHQL_URL",
    "PER_PAGE",
    "REQUEST_TIMEOUT",
    "MAX_RETRIES",
    "BACKOFF_BASE_SEC",
    "OUTPUT_DIR",
    "MAX_PAGES_COMMITS",
    "MAX_WAIT_ON_403",
    "RATE_LIMIT_TOKEN_RESET_WAIT_SEC",
    "INCREMENTAL_LOOKBACK_SEC",
    "BLAME_EXAMPLE_LIMIT",
    "BLAME_FILE_LIMIT",
    "REPOS",
]
