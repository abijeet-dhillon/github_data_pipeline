"""
test_rest_pipeline.py
---------------------
Comprehensive unit tests for `rest_pipeline.py`.

These tests validate core functionality of the GitHub REST data pipeline,
including pagination, authentication handling, rate-limit backoff, data retrieval,
issue and PR linking, and cross-repository reference detection.

Test Coverage:
    • HTTP request handling and retry logic
    • Pagination and error responses
    • Repository metadata, issues, PRs, commits, and comments retrieval
    • Issue and PR parsing, linkage extraction, and cross-repo references
    • Utility helpers (JSON save, directory creation, regex extractors)
    • Orchestration functions (`process_repo`, `main`)

Usage:
    Run all tests with coverage reporting:
        pytest -v --cov=rest_pipeline --cov-report=term-missing
"""


import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import pytest
import requests
import rest_pipeline as pipeline
from unittest.mock import patch, MagicMock


# helpers
def make_resp(status=200, payload=None, headers=None, content_type_json=True):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    if content_type_json:
        r.headers.setdefault("content-type", "application/json")
    if payload is None:
        payload = {}
    r.json.return_value = payload
    r.text = json.dumps(payload)
    return r


def test_parse_full_repo():
    assert pipeline._parse_full_repo("x/y") == ("x", "y")


def test_classify_issue_or_pr():
    assert pipeline.classify_issue_or_pr({"pull_request": {"x": 1}}) == "pull_request"
    assert pipeline.classify_issue_or_pr({}) == "issue"


def test_source_text_buckets_for_issue_like():
    issue = {"number": 1, "title": "T", "body": "B", "created_at": "t0"}
    buckets = list(pipeline._source_text_buckets_for_issue_like("o", "r", issue))
    assert ("issue_title", "T", "t0") in buckets
    assert ("issue_body", "B", "t0") in buckets


# sleep + logging
def testsleep_with_jitter(monkeypatch):
    called = {}
    monkeypatch.setattr("time.sleep", lambda x: called.setdefault("val", x))
    pipeline.sleep_with_jitter(1.5)
    assert "val" in called and isinstance(called["val"], float)


def test_log_http_error_json_and_text(capsys):
    resp = make_resp(403, {"message": "bad"})
    pipeline._log_http_error(resp, "url")
    out = capsys.readouterr().out
    assert "bad" in out
    resp = make_resp(403, None)
    resp.text = "hello"
    resp.json.side_effect = ValueError()
    pipeline._log_http_error(resp, "url")
    assert "hello" in capsys.readouterr().out


# auth switching
def test_set_auth_header_and_switch(monkeypatch):
    pipeline.GITHUB_TOKENS[:] = ["t1", "t2"]
    pipeline.GITHUB_TOKEN_INDEX = 0
    pipeline._set_auth_header_for_current_token()
    assert "Authorization" in pipeline.SESSION.headers
    assert pipeline._switch_to_next_token() is True
    assert pipeline.GITHUB_TOKEN_INDEX == 1
    pipeline.GITHUB_TOKEN_INDEX = 1
    assert pipeline._switch_to_next_token() is False


# _request(): success + retry logic
@patch("rest_pipeline.SESSION")
def test_request_success(mock_session):
    mock_session.request.return_value = make_resp(200, {"ok": 1})
    r = pipeline._request("GET", "https://api.github.com/x")
    assert r.status_code == 200


@patch("rest_pipeline.sleep_with_jitter", lambda *_: None)
@patch("rest_pipeline.SESSION")
def test_request_retry_on_exception(mock_session):
    mock_session.request.side_effect = [
        requests.RequestException("boom"),
        make_resp(200, {"ok": 1}),
    ]
    out = pipeline._request("GET", "url")
    assert out.status_code == 200


@patch("rest_pipeline.sleep_with_jitter", lambda *_: None)
@patch("rest_pipeline.SESSION")
def test_request_rate_limit_switch_token(mock_session):
    pipeline.GITHUB_TOKENS[:] = ["t1", "t2"]
    pipeline.GITHUB_TOKEN_INDEX = 0
    r1 = make_resp(403, {"message": ""}, headers={"X-RateLimit-Remaining": "0"})
    r2 = make_resp(200, {"ok": True})
    mock_session.request.side_effect = [r1, r2]
    out = pipeline._request("GET", "url")
    assert out.status_code == 200


@patch("rest_pipeline.sleep_with_jitter", lambda *_: None)
@patch("rest_pipeline.SESSION")
def test_request_retry_after_wait(mock_session):
    r1 = make_resp(403, {"message": ""}, headers={"Retry-After": "1"})
    r2 = make_resp(200, {"ok": True})
    mock_session.request.side_effect = [r1, r2]
    out = pipeline._request("GET", "url")
    assert out.status_code == 200


@patch("rest_pipeline.sleep_with_jitter", lambda *_: None)
@patch("rest_pipeline.SESSION")
def test_request_terminal_4xx(mock_session):
    mock_session.request.return_value = make_resp(404, {"message": "x"})
    r = pipeline._request("GET", "u")
    assert r.status_code == 404


# _paged_get
@patch("rest_pipeline._request")
def test_paged_get_two_pages(mock_request, monkeypatch):
    monkeypatch.setattr(pipeline, "PER_PAGE", 2)
    mock_request.side_effect = [
        make_resp(200, [{"id": 1}, {"id": 2}]),
        make_resp(200, [{"id": 3}]),
    ]
    res = pipeline._paged_get("url", "o", "r")
    assert [r["id"] for r in res] == [1, 2, 3]


@patch("rest_pipeline._request")
def test_paged_get_non200(mock_request):
    mock_request.return_value = make_resp(403, {"message": "bad"})
    res = pipeline._paged_get("url", "o", "r")
    assert res == []


# data retrieval
@patch("rest_pipeline._request", return_value=make_resp(200, {"full_name": "a/b"}))
def test_get_repo_meta_ok(mock_req):
    out = pipeline.get_repo_meta("a", "b")
    assert out["repo_name"] == "a/b"


@patch("rest_pipeline._request", return_value=make_resp(404, {"x": 1}))
def test_get_repo_meta_fail(mock_req):
    out = pipeline.get_repo_meta("a", "b")
    assert out["repo_name"] == "a/b"


@patch("rest_pipeline._paged_get", return_value=[{"id": 1}, {"pull_request": {}}])
def test_get_issues_filters(mock_pg):
    out = pipeline.get_issues("o", "r")
    assert all("pull_request" not in i for i in out)


@patch("rest_pipeline._paged_get", return_value=[{"id": 1}])
def test_get_pull_requests_and_commits_and_comments(mock_pg):
    assert pipeline.get_pull_requests("o", "r")
    assert pipeline.get_commits("o", "r")
    assert pipeline.get_issue_comments("o", "r", 1)


@patch("rest_pipeline._request", return_value=make_resp(200, {"ok": 1}))
def test_get_commit_detail_ok(mock_r):
    out = pipeline.get_commit_detail("o", "r", "sha")
    assert out == {"ok": 1}


@patch("rest_pipeline._request")
def test_get_commit_detail_invalid_sha(mock_req):
    pipeline.COMMIT_CACHE.clear()  
    mock_req.return_value = MagicMock(status_code=422)
    mock_req.return_value.json.return_value = {"message": "no commit"}
    out = pipeline.get_commit_detail("o", "r", "sha")
    assert out == {"error": "invalid_sha"}


@patch("rest_pipeline._request")
def test_get_commit_detail_fail(mock_req):
    pipeline.COMMIT_CACHE.clear()
    mock_req.return_value = MagicMock(status_code=404)
    mock_req.return_value.json.return_value = {"msg": "x"}
    out = pipeline.get_commit_detail("o", "r", "sha")
    assert out == {}


def test_get_commit_message_cases():
    assert pipeline.get_commit_message({"commit": {"message": "hi"}}) == "hi"
    assert pipeline.get_commit_message({"commit": {}}) == ""
    assert pipeline.get_commit_message({}) == ""


# regex extractors
def test_extract_issue_refs_detailed_basic():
    refs = pipeline.extract_issue_refs_detailed("Fixes #1 and closes a/b#2")
    nums = [r["number"] for r in refs]
    assert 1 in nums and 2 in nums


def test_extract_issue_refs_no_text():
    assert pipeline.extract_issue_refs_detailed("") == []


def test_extract_issue_refs_without_kw():
    refs = pipeline.extract_issue_refs_detailed("related to #3 only")
    assert refs and not refs[0]["has_closing_kw"]


# find_prs_with_linked_issues
@patch("rest_pipeline.get_commit_detail", return_value={"commit": {"message": "resolves o/r#4"}})
@patch("rest_pipeline.get_pr_commits", return_value=[{"commit": {"message": "Fixes #3"}}])
@patch("rest_pipeline.extract_issue_refs_detailed")
def test_find_prs_with_linked_issues(mock_extract, *_mocks):
    mock_extract.side_effect = lambda text: [{"full_repo": None, "number": 1, "has_closing_kw": True}] if text else []
    pr = {
        "number": 10, "title": "Fixes #1", "body": "closes o/r#2",
        "merged_at": "now", "user": {"login": "author"}, "html_url": "url",
        "state": "closed", "created_at": "t0", "merge_commit_sha": "sha"
    }
    out = pipeline.find_prs_with_linked_issues("o", "r", [pr], local_issues=[{"number": 1, "user": {"login": "a"}}])
    assert out and out[0]["repo_name"] == "o/r"


# find_issues_closed_by_repo_commits
@patch("rest_pipeline.get_issue_or_pr_details", return_value={"user": {"login": "u"}})
def test_find_issues_closed_by_repo_commits(mock_d):
    commits = [
        {"sha": "a1", "html_url": "u1", "author": {"login": "x"}, "commit": {"message": "fixes #1"}},
        {"sha": "a2", "html_url": "u2", "commit": {"author": {"name": "y"}, "message": "closes a/b#2"}},
    ]
    out = pipeline.find_issues_closed_by_repo_commits("a", "b", commits)
    assert all(r["would_auto_close"] for r in out)
    assert any(r["issue_number"] == 1 for r in out)


# cross-project linking
@patch("rest_pipeline.get_issue_or_pr_details")
def test_find_cross_project_links(mock_d):
    mock_d.return_value = {"html_url": "h", "created_at": "t", "user": {"login": "x"}}
    issues = [{"number": 1, "title": "refs ext/repo#9", "body": "", "created_at": "t1", "html_url": "u"}]
    prs = [{"number": 2, "title": "", "body": "mentions ext/repo#10", "created_at": "t2", "html_url": "u2"}]
    res = pipeline.find_cross_project_links_issues_and_prs("a", "b", issues, prs)
    assert res and "source" in res[0]


# ensure_dir + save_json
def test_ensure_dir_and_save_json(tmp_path):
    d = tmp_path / "sub"
    pipeline.ensure_dir(str(d))
    f = d / "file.json"
    pipeline.save_json(f, {"x": 1})
    assert json.load(open(f)) == {"x": 1}


# process_repo + main orchestration
@patch("rest_pipeline.get_repo_meta", return_value={"repo_name": "r"})
@patch("rest_pipeline.get_issues", return_value=[{"id": 1}])
@patch("rest_pipeline.get_pull_requests", return_value=[{"id": 2}])
@patch("rest_pipeline.get_commits", return_value=[{"id": 3}])
@patch("rest_pipeline.find_prs_with_linked_issues", return_value=[{"id": 4}])
@patch("rest_pipeline.find_issues_closed_by_repo_commits", return_value=[{"id": 5}])
@patch("rest_pipeline.find_cross_project_links_issues_and_prs", return_value=[{"id": 6}])
def test_process_repo_calls_all(m1, m2, m3, m4, m5, m6, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", str(tmp_path))
    pipeline.process_repo("o/r")
    for m in (m1, m2, m3, m4, m5, m6):
        m.assert_called()


def test_main_no_repos(monkeypatch):
    monkeypatch.setattr(pipeline, "REPOS", [])
    with pytest.raises(SystemExit):
        pipeline.main([])


@patch("rest_pipeline.process_repo")
def test_main_custom_repos(mock_proc):
    pipeline.main(["a/b", "c/d"])
    mock_proc.assert_any_call("a/b")
    mock_proc.assert_any_call("c/d")