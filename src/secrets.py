"""Utilities for loading local (gitignored) credentials."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_SECRETS_FILENAME = "local_secrets.json"


def _default_secrets_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / DEFAULT_SECRETS_FILENAME


def load_local_secrets(path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Load secrets from a JSON file; return {} when unavailable."""

    candidate = path or os.getenv("LOCAL_SECRETS_FILE") or _default_secrets_path()
    secrets_path = Path(candidate).expanduser()
    if not secrets_path.exists():
        return {}
    try:
        with secrets_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


__all__ = ["load_local_secrets", "DEFAULT_SECRETS_FILENAME"]
