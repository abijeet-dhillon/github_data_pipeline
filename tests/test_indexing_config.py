"""Tests for src.indexing.config covering CLI parsing and hardlock behavior.

Run with coverage:
    pytest tests/test_indexing_config.py --maxfail=1 -v --cov=src.indexing.config --cov-report=term-missing
"""

from pathlib import Path

from src.indexing import config


def test_resolve_settings_uses_hardcoded_defaults(monkeypatch):
    monkeypatch.setattr(config, "HARDLOCK", True)
    settings = config.resolve_settings()
    assert settings.data_dir == Path(config.HARDCODED_DATA_DIR)
    assert settings.es_url == config.HARDCODED_ES_URL
    assert settings.batch_size == config.HARDCODED_BATCH_SIZE
    assert settings.dry_run is False


def test_resolve_settings_from_cli(monkeypatch):
    monkeypatch.setattr(config, "HARDLOCK", False)
    args = config.parse_args([
        "--data-dir",
        "./custom",
        "--es-url",
        "http://example.com",
        "--username",
        "user",
        "--password",
        "pass",
        "--api-key",
        "key",
        "--verify-tls",
        "--prefix",
        "pref_",
        "--batch-size",
        "5",
        "--dry-run",
    ])
    settings = config.resolve_settings(args)
    assert settings.data_dir == Path("./custom")
    assert settings.es_url == "http://example.com"
    assert settings.username == "user"
    assert settings.password == "pass"
    assert settings.api_key == "key"
    assert settings.verify_tls is True
    assert settings.prefix == "pref_"
    assert settings.batch_size == 5
    assert settings.dry_run is True
