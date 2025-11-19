"""Tests for src.indexing.runner to ensure configuration wires into scan_and_index.

Run with coverage:
    pytest tests/test_indexing_runner.py --maxfail=1 -v --cov=src.indexing.runner --cov-report=term-missing
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.indexing import runner


@patch("src.indexing.runner.scan_and_index")
@patch("src.indexing.runner._build_client")
@patch("src.indexing.runner.resolve_settings")
@patch("src.indexing.runner.parse_args")
def test_main_invokes_scan(parse_args, resolve_settings, build_client, scan):
    parse_args.return_value = MagicMock()
    resolve_settings.return_value = MagicMock(
        data_dir=Path("./data"),
        es_url="http://localhost:9200",
        username=None,
        password=None,
        api_key=None,
        verify_tls=False,
        prefix="pref_",
        batch_size=10,
        dry_run=False,
    )
    build_client.return_value = MagicMock()

    runner.main([])

    assert parse_args.called
    assert resolve_settings.called
    assert build_client.called
    assert scan.called
