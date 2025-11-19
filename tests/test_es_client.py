"""Tests for src.indexing.client exercising ESClient behavior and bulk uploads.

Run with coverage:
    pytest tests/test_es_client.py --maxfail=1 -v --cov=src.indexing.client --cov-report=term-missing
"""

import json
from unittest.mock import MagicMock, patch

from src.indexing.client import ESClient


@patch("src.indexing.client.requests.Session")
def test_ensure_index_creates_when_missing(mock_session):
    session = MagicMock()
    mock_session.return_value = session
    session.head.return_value.status_code = 404
    session.put.return_value.status_code = 200
    client = ESClient("http://localhost:9200", None, None, None, verify_tls=False)
    client.ensure_index("demo", {"mappings": {}})
    assert session.put.called


@patch("src.indexing.client.requests.Session")
def test_bulk_index_counts_success_and_failures(mock_session):
    session = MagicMock()
    mock_session.return_value = session
    response_ok = MagicMock()
    response_ok.status_code = 200
    response_ok.json.return_value = {"items": [{"index": {"status": 201}}]}
    response_fail = MagicMock()
    response_fail.status_code = 200
    response_fail.json.return_value = {
        "items": [{"index": {"status": 500, "error": {"reason": "boom"}}}]
    }
    session.post.side_effect = [response_ok, response_fail]

    client = ESClient("http://localhost:9200", None, None, None, verify_tls=False)
    ok, fail = client.bulk_index("demo", [{"id": 1}, {"id": 2}], id_func=lambda doc: str(doc["id"]), batch_size=1)
    assert ok == 1
    assert fail == 1
