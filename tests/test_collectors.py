"""Tests for src.retrieval.collectors covering helpers and REST fetchers.

Run with coverage to exercise the data collection logic:
    pytest tests/test_collectors.py --maxfail=1 -v --cov=src.retrieval.collectors --cov-report=term-missing
"""

import json
from unittest.mock import MagicMock, patch

from src.retrieval import collectors


def _resp(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = json.dumps(payload or {})
    return resp


def test_author_key_and_one_line_helpers():
    author = collectors.author_key_from_commit_author({"user": {"login": "z"}})
    assert author == "z"
    assert collectors.one_line("first\nsecond") == "first"


def test_save_json_round_trip(tmp_path):
    data = {"hello": "world"}
    out = tmp_path / "data.json"
    collectors.ensure_dir(tmp_path)
    collectors.save_json(out, data)
    loaded = json.loads(out.read_text())
    assert loaded == data


@patch("src.retrieval.collectors.request_with_backoff", return_value=_resp(200, {"full_name": "a/b"}))
def test_get_repo_meta_success(mock_request):
    meta = collectors.get_repo_meta("a", "b")
    assert meta["repo_name"] == "a/b"
    mock_request.assert_called_once()


@patch("src.retrieval.collectors.paged_get", return_value=[{"id": 1}, {"pull_request": {}}, {"id": 2}])
@patch("src.retrieval.collectors._load_cached_list", return_value=[])
def test_get_issues_filters_prs(mock_cache, mock_paged):
    issues = collectors.get_issues("o", "r")
    assert all("pull_request" not in issue for issue in issues)


@patch("src.retrieval.collectors.request_with_backoff")
def test_get_commit_detail_caches(mock_request):
    mock_request.return_value = _resp(200, {"sha": "abc", "files": [], "stats": {}})
    collectors.COMMIT_CACHE.clear()
    first = collectors.get_commit_detail("o", "r", "abc")
    assert first["sha"] == "abc"
    second = collectors.get_commit_detail("o", "r", "abc")
    assert second == first
    assert mock_request.call_count == 1


@patch("src.retrieval.collectors.get_commit_detail", return_value={"files": [], "stats": {}})
@patch("src.retrieval.collectors.paged_get")
@patch("src.retrieval.collectors._load_cached_list", return_value=[])
def test_get_commits_non_incremental(mock_cache, mock_paged, mock_detail):
    mock_paged.return_value = [{"sha": "1", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}}]
    commits = collectors.get_commits("o", "r")
    assert commits[0]["sha"] == "1"
    mock_paged.assert_called_once()
