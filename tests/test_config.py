"""Tests for src.pipeline.config ensuring env overrides and defaults work.

Run with coverage to validate configuration handling:
    pytest tests/test_config.py --maxfail=1 -v --cov=src.pipeline.config --cov-report=term-missing
"""

from importlib import reload
import os

import src.pipeline.config as config


def test_config_defaults_are_present():
    assert isinstance(config.REPOS, list) and config.REPOS
    assert config.PER_PAGE > 0
    assert config.BACKOFF_BASE_SEC >= 1
    assert config.USER_AGENT.startswith("cosc448")


def test_env_override_for_max_pages(monkeypatch):
    monkeypatch.setenv("MAX_PAGES_COMMITS", "9")
    reloaded = reload(config)
    try:
        assert reloaded.MAX_PAGES_COMMITS == 9
    finally:
        monkeypatch.delenv("MAX_PAGES_COMMITS", raising=False)
        reload(config)
