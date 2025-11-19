"""Tests for src.indexing.indexer covering JSON helpers and scan orchestration.

Run with:
    pytest tests/test_indexer.py --maxfail=1 -v --cov=src.indexing.indexer --cov-report=term-missing
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

from src.indexing import indexer


def test_folder_repo_name_and_repo_field_helpers(tmp_path):
    folder = tmp_path / "owner_repo"
    folder.mkdir()
    assert indexer.folder_repo_name(folder) == "owner/repo"

    doc = {}
    indexer.ensure_repo_name_field(doc, "owner/repo")
    assert doc["repo_name"] == "owner/repo"


def test_iter_json_accepts_object_and_list(tmp_path):
    list_file = tmp_path / "list.json"
    list_file.write_text(json.dumps([{"id": 1}]))
    assert list(indexer.iter_json(list_file))[0]["id"] == 1

    dict_file = tmp_path / "dict.json"
    dict_file.write_text(json.dumps({"id": 2}))
    assert list(indexer.iter_json(dict_file))[0]["id"] == 2


def test_scan_and_index_invokes_bulk(tmp_path, monkeypatch):
    repo_dir = tmp_path / "owner_repo"
    repo_dir.mkdir()
    issues_file = repo_dir / "issues.json"
    issues_file.write_text(json.dumps([{"number": 1}]))

    mock_es = MagicMock()
    mock_es.bulk_index.return_value = (1, 0)

    monkeypatch.setattr(indexer, "FILE_TO_INDEX", {"issues.json": ("issues", lambda doc: "id")})
    monkeypatch.setattr(indexer, "MAPPINGS", {"issues": {}})

    indexer.scan_and_index(mock_es, data_dir=tmp_path, index_prefix="pref_", dry_run=False, batch_size=10)

    mock_es.ensure_index.assert_called_once_with("pref_issues", {})
    mock_es.bulk_index.assert_called_once()
