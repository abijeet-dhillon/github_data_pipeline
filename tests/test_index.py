"""
Tests for index_elasticsearch.py covering helpers, ES client behavior,
and scan-and-index orchestration.

Running these tests (with coverage):
    pytest tests/test_index.py --maxfail=1 -v --cov=index_elasticsearch --cov-report=term-missing
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import index_elasticsearch as indexer


def test_folder_repo_name_and_repo_field_helpers():
    assert indexer.folder_repo_name(type("P", (), {"name": "owner_repo"})()) == "owner/repo"
    assert indexer.folder_repo_name(type("P", (), {"name": "already/there"})()) == "already/there"

    doc = {}
    indexer.ensure_repo_name_field(doc, "o/r")
    assert doc["repo_name"] == "o/r"
    doc = {"repo_name": "custom"}
    indexer.ensure_repo_name_field(doc, "ignored")
    assert doc["repo_name"] == "custom"


def test_iter_json_handles_multiple_shapes(tmp_path):
    list_file = tmp_path / "list.json"
    list_file.write_text(json.dumps([{"id": 1}]))
    assert list(indexer.iter_json(list_file)) == [{"id": 1}]

    dict_file = tmp_path / "dict.json"
    dict_file.write_text(json.dumps({"id": 2}))
    assert list(indexer.iter_json(dict_file)) == [{"id": 2}]

    scalar_file = tmp_path / "scalar.json"
    scalar_file.write_text(json.dumps("text"))
    assert list(indexer.iter_json(scalar_file)) == [{"raw": "text"}]


@patch("index_elasticsearch.requests.Session")
def test_esclient_ensure_index_and_bulk_index(mock_session):
    session = MagicMock()
    mock_session.return_value = session
    session.head.return_value.status_code = 404
    session.put.return_value.status_code = 200
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "items": [
            {"index": {"status": 201}},
            {"index": {"error": {"reason": "boom"}}},
        ]
    }
    session.post.return_value = resp

    es = indexer.ESClient("http://localhost:9200", None, None, None, verify_tls=False)
    es.ensure_index("demo", {"mappings": {}})
    session.put.assert_called_once()

    ok, fail = es.bulk_index("demo", [{"id": 1}, {"id": 2}], id_func=lambda d: str(d["id"]))
    assert ok == 1 and fail == 1
    assert session.post.called


def test_scan_and_index_inserts_repo_name(tmp_path):
    repo_folder = tmp_path / "owner_repo"
    repo_folder.mkdir()
    issues_file = repo_folder / "issues.json"
    issues_file.write_text(json.dumps([{"id": 1, "repo_name": ""}]))

    class DummyES:
        def __init__(self):
            self.bulk_calls = []

        def ensure_index(self, name, mapping):
            self.bulk_calls.append(("ensure", name))

        def bulk_index(self, index, docs, id_func=None, batch_size=1000):
            docs = list(docs)
            self.bulk_calls.append(("bulk", index, docs))
            return (len(docs), 0)

    es = DummyES()
    indexer.scan_and_index(es, data_dir=tmp_path, index_prefix="pref_", dry_run=False, batch_size=10)

    bulk_calls = [entry for entry in es.bulk_calls if entry[0] == "bulk"]
    assert bulk_calls, "Expected scan_and_index to call bulk_index"
    _, idx_name, docs = bulk_calls[0]
    assert idx_name == "pref_issues"
    assert docs[0]["repo_name"] == "owner/repo"
