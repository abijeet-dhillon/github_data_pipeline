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


@patch("src.retrieval.collectors.get_commit_detail")
def test_lookup_commit_for_blame_fetches_and_caches(mock_detail):
    mock_detail.return_value = {
        "files": [{"filename": "file.txt"}],
        "commit": {"author": {"name": "dev"}},
    }
    lookup = {}
    result = collectors._lookup_commit_for_blame(lookup, "o", "r", "sha")
    assert result["files_changed"] == ["file.txt"]
    assert lookup["sha"]["files_changed_count"] == 1


@patch("src.retrieval.collectors._lookup_commit_for_blame", return_value=None)
def test_summarize_blame_ranges_accumulates(mock_lookup):
    ranges = [{
        "startingLine": 1,
        "endingLine": 2,
        "commit": {
            "author": {"user": {"login": "dev"}},
            "oid": "sha",
            "committedDate": "2024-01-01T00:00:00Z",
            "message": "msg\nmore"
        }
    }]
    summary = collectors.summarize_blame_ranges(ranges, {}, "o", "r")
    assert summary["total_lines"] == 2
    assert summary["ranges_count"] == 1
    assert summary["examples"]


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


@patch("src.retrieval.collectors.run_graphql_query")
def test_fetch_file_blame_prefers_ref(mock_query):
    mock_query.return_value = {
        "repository": {
            "ref": {
                "target": {
                    "__typename": "Commit",
                    "oid": "root",
                    "blame": {"ranges": [{"startingLine": 1}]},
                }
            }
        }
    }
    result = collectors.fetch_file_blame("o", "r", "main", "f")
    assert result["root_commit_oid"] == "root"
    assert result["ranges"] == [{"startingLine": 1}]


@patch("src.retrieval.collectors.run_graphql_query")
def test_fetch_file_blame_fallback_on_error(mock_query):
    mock_query.side_effect = [
        RuntimeError("boom"),
        {"repository": {"object": {"__typename": "Commit", "oid": "fallback", "blame": {"ranges": []}}}},
    ]
    result = collectors.fetch_file_blame("o", "r", "main", "f")
    assert result["root_commit_oid"] == "fallback"


def test_collect_repo_blame_without_tokens(monkeypatch):
    monkeypatch.setattr(collectors, "GITHUB_TOKENS", [])
    out = collectors.collect_repo_blame("o", "r", {"default_branch": "main"}, [])
    assert out["error"].startswith("GitHub token")


@patch("src.retrieval.collectors._load_cached_dict", return_value={})
@patch("src.retrieval.collectors.list_repo_files", return_value=["a.py"])
@patch("src.retrieval.collectors.fetch_file_blame", return_value={"ranges": [{"startingLine": 1, "endingLine": 1, "commit": {"author": {}, "oid": "sha", "committedDate": "d", "message": "m"}}], "root_commit_oid": "root"})
@patch("src.retrieval.collectors.summarize_blame_ranges", return_value={"ranges_count": 0, "total_lines": 0, "authors": [], "examples": []})
def test_collect_repo_blame_writes_entries(mock_summary, mock_fetch, mock_list, mock_cache, monkeypatch):
    monkeypatch.setattr(collectors, "GITHUB_TOKENS", ["tok"])
    out = collectors.collect_repo_blame("o", "r", {"default_branch": "main"}, [])
    assert out["files"][0]["path"] == "a.py"


def test_cached_blame_head_sha_prefers_files():
    doc = {"files": [{"root_commit_oid": "abc"}]}
    assert collectors._cached_blame_head_sha(doc) == "abc"


@patch("src.retrieval.collectors.request_with_backoff")
def test_list_repo_files_returns_blobs(mock_request):
    mock_request.return_value = _resp(200, {
        "tree": [
            {"type": "blob", "path": "README.md"},
            {"type": "tree", "path": "docs"}
        ],
        "truncated": False,
    })
    files = collectors.list_repo_files("o", "r", "main")
    assert files == ["README.md"]


@patch("src.retrieval.collectors.request_with_backoff")
def test_list_repo_files_handles_errors(mock_request):
    mock_request.return_value = _resp(404, {})
    files = collectors.list_repo_files("o", "r", "main")
    assert files == []


@patch("src.retrieval.collectors.request_with_backoff")
def test_get_changed_files_between_refs(mock_request):
    mock_request.return_value = _resp(200, {
        "files": [
            {"filename": "a.txt", "status": "modified", "previous_filename": "old_a.txt"}
        ]
    })
    changed = collectors._get_changed_files_between_refs("o", "r", "base", "head")
    assert changed == [{"path": "a.txt", "status": "modified", "previous": "old_a.txt"}]


def test_max_timestamp_helpers():
    docs = [{"updated_at": "2024-02-01T00:00:00Z"}, {"created_at": "2024-03-01T00:00:00Z"}]
    result = collectors._max_timestamp_from_docs(docs, ["updated_at", "created_at"])
    assert result.isoformat() == "2024-03-01T00:00:00"


def test_max_commit_timestamp_prefers_latest():
    commits = [
        {"commit": {"author": {"date": "2024-01-01T00:00:00Z"}}},
        {"commit": {"committer": {"date": "2024-05-01T00:00:00Z"}}},
    ]
    result = collectors._max_commit_timestamp(commits)
    assert result.isoformat() == "2024-05-01T00:00:00"
