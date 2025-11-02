"""
test_pipeline.py
----------------
Unit tests for initial_pipeline.py targeting ~90%+ coverage.

Run with:
    pytest -v --cov=initial_pipeline --cov-report=term-missing
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import pytest
import requests
from unittest.mock import patch, MagicMock

import initial_pipeline as pipeline


# ---------------------------------------------------------------------
# Helpers for making mock Response objects
# ---------------------------------------------------------------------
def make_resp(status=200, payload=None, headers=None, content_type_json=True):
    """Create a minimal Response-like mock."""
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    if content_type_json:
        r.headers.setdefault("content-type", "application/json")
    if payload is None:
        payload = {}
    r.json.return_value = payload
    return r


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------
@pytest.fixture
def mock_response():
    """Return a mock 200 repo meta Response-like object."""
    return make_resp(200, {"full_name": "octocat/Hello-World"})


# ---------------------------------------------------------------------
# _sleep_with_jitter
# ---------------------------------------------------------------------
def test_sleep_with_jitter(monkeypatch):
    called = {}
    monkeypatch.setattr("time.sleep", lambda x: called.setdefault("val", x))
    pipeline._sleep_with_jitter(1.5)
    assert "val" in called and isinstance(called["val"], float)


# ---------------------------------------------------------------------
# _request(): success, retry on exception, rate limit & abuse, server error
# ---------------------------------------------------------------------
@patch("initial_pipeline.SESSION")
def test_request_success(mock_session, mock_response):
    mock_session.request.return_value = mock_response
    result = pipeline._request("GET", "https://api.github.com/test")
    assert result.status_code == 200
    mock_session.request.assert_called_once()


@patch("initial_pipeline._sleep_with_jitter", lambda *_args, **_kw: None)
@patch("initial_pipeline.SESSION")
def test_request_raises_and_retries(mock_session):
    """Retries when a requests.RequestException is raised."""
    mock_session.request.side_effect = [
        requests.RequestException("boom"),
        make_resp(200, {"ok": True}),
    ]
    # keep tests fast
    pipeline.BACKOFF_BASE_SEC = 0.0
    pipeline.MAX_RETRIES = 3
    out = pipeline._request("GET", "https://api.github.com/x")
    assert out.status_code == 200


@patch("initial_pipeline._sleep_with_jitter", lambda *_args, **_kw: None)
@patch("initial_pipeline.SESSION")
def test_request_rate_limit_retry_after(mock_session):
    """403 + Retry-After triggers a sleep+retry loop, then success."""
    r1 = make_resp(
        403,
        {"message": ""},
        headers={"Retry-After": "1", "content-type": "application/json"},
    )
    r2 = make_resp(200, {"ok": True})
    mock_session.request.side_effect = [r1, r2]

    # avoid real sleep
    called = {"slept": 0}
    def fake_sleep(x):
        called["slept"] += 1
    with patch("time.sleep", fake_sleep):
        out = pipeline._request("GET", "https://api.github.com/x")
    assert out.status_code == 200
    assert called["slept"] >= 1


@patch("initial_pipeline._sleep_with_jitter", lambda *_args, **_kw: None)
@patch("initial_pipeline.SESSION")
def test_request_abuse_detection_backoff(mock_session):
    """403 with 'abuse detection' in JSON message triggers backoff then retry."""
    abuse = make_resp(
        403,
        {"message": "You have triggered an abuse detection mechanism"},
        headers={"content-type": "application/json"},
    )
    ok = make_resp(200, {"ok": True})

    mock_session.request.side_effect = [abuse, ok]
    pipeline.BACKOFF_BASE_SEC = 0.0
    out = pipeline._request("GET", "https://api.github.com/y")
    assert out.status_code == 200


@patch("initial_pipeline._sleep_with_jitter", lambda *_args, **_kw: None)
@patch("initial_pipeline.SESSION")
def test_request_server_error_then_success(mock_session):
    """5xx errors raise inside loop and then succeed on retry."""
    r500 = make_resp(500, {"message": "server error"})
    ok = make_resp(200, {"ok": True})
    # first call returns 500 (pipeline raises RequestException and retries),
    # second call returns 200
    mock_session.request.side_effect = [r500, ok]
    pipeline.BACKOFF_BASE_SEC = 0.0
    pipeline.MAX_RETRIES = 2
    out = pipeline._request("GET", "https://api.github.com/z")
    assert out.status_code == 200


# ---------------------------------------------------------------------
# _paged_get(): multi-page, non-200 short-circuit
# ---------------------------------------------------------------------
@patch("initial_pipeline._request")
def test_paged_get_multiple_pages(mock_request, monkeypatch):
    # Ensure first page length == PER_PAGE so that pagination continues
    monkeypatch.setattr(pipeline, "PER_PAGE", 2)

    r1 = make_resp(200, [{"id": 1}, {"id": 2}])  # length == PER_PAGE → continue
    r2 = make_resp(200, [{"id": 3}])             # length < PER_PAGE → stop
    mock_request.side_effect = [r1, r2]

    data = pipeline._paged_get("https://api.github.com/x", "o", "r")
    assert [d["id"] for d in data] == [1, 2, 3]
    assert all(d["repo_name"] == "o/r" for d in data)


@patch("initial_pipeline._request")
def test_paged_get_warn_on_non_200_breaks(mock_request):
    mock_request.return_value = make_resp(404, {"message": "nope"})
    out = pipeline._paged_get("https://api.github.com/x", "o", "r")
    assert out == []


# ---------------------------------------------------------------------
# Data retrieval wrappers
# ---------------------------------------------------------------------
@patch("initial_pipeline._request")
def test_get_repo_meta(mock_request):
    mock_request.return_value = make_resp(200, {"full_name": "octo/cat"})
    out = pipeline.get_repo_meta("octo", "cat")
    assert out["repo_name"] == "octo/cat"


@patch("initial_pipeline._request")
def test_get_repo_meta_non_200_returns_empty(mock_request):
    mock_request.return_value = make_resp(404, {"message": "not found"})
    out = pipeline.get_repo_meta("o", "r")
    assert out == {}


@patch("initial_pipeline._paged_get")
def test_get_issues_filters_prs(mock_paged):
    mock_paged.return_value = [{"id": 1, "pull_request": {}}, {"id": 2}]
    result = pipeline.get_issues("o", "r")
    assert [i["id"] for i in result] == [2]


@patch("initial_pipeline._paged_get", return_value=[{"id": 1}])
def test_get_pull_requests(mock_paged):
    assert pipeline.get_pull_requests("o", "r") == [{"id": 1}]
    mock_paged.assert_called_once()


@patch("initial_pipeline._paged_get", return_value=[{"id": 1}])
def test_get_commits(mock_paged):
    assert pipeline.get_commits("o", "r") == [{"id": 1}]


@patch("initial_pipeline._paged_get", return_value=[{"id": 1}])
def test_get_issue_comments(mock_paged):
    assert pipeline.get_issue_comments("o", "r", 99) == [{"id": 1}]


@patch("initial_pipeline._request", return_value=make_resp(200, {"ok": True}))
def test_get_commit_detail_ok(mock_req):
    out = pipeline.get_commit_detail("o", "r", "sha")
    assert out == {"ok": True}


@patch("initial_pipeline._request", return_value=make_resp(404, {"message": "x"}))
def test_get_commit_detail_non_200(mock_req):
    out = pipeline.get_commit_detail("o", "r", "sha")
    assert out == {}


def test_get_commit_message():
    assert pipeline.get_commit_message({"commit": {"message": "hi"}}) == "hi"
    assert pipeline.get_commit_message({"commit": {}}) == ""
    assert pipeline.get_commit_message({}) == ""


# ---------------------------------------------------------------------
# Regex extractors
# ---------------------------------------------------------------------
def test_extract_issue_refs_detailed_basic():
    text = "Fixes #42 and closes user/repo#99"
    refs = pipeline.extract_issue_refs_detailed(text)
    nums = {r["number"] for r in refs}
    assert 42 in nums and 99 in nums
    assert any(r["has_closing_kw"] for r in refs)


def test_extract_issue_refs_detailed_no_text():
    assert pipeline.extract_issue_refs_detailed("") == []


def test_extract_issue_refs_detailed_without_kw():
    text = "related to #77 but not closing"
    refs = pipeline.extract_issue_refs_detailed(text)
    assert any(not r["has_closing_kw"] for r in refs)
    assert any(r["number"] == 77 for r in refs)


# ---------------------------------------------------------------------
# Cross-project: helpers & classification
# ---------------------------------------------------------------------
def test_parse_full_repo():
    assert pipeline._parse_full_repo("octocat/hello") == ("octocat", "hello")


def test_classify_issue_or_pr():
    # In this implementation, an empty {} is falsy → 'issue'
    assert pipeline.classify_issue_or_pr({"pull_request": {}}) == "issue"
    # Non-empty dict is truthy → 'pull_request'
    assert pipeline.classify_issue_or_pr({"pull_request": {"url": "x"}}) == "pull_request"
    assert pipeline.classify_issue_or_pr({}) == "issue"


@patch("initial_pipeline.get_issue_comments")
def test_source_text_buckets(mock_comments):
    mock_comments.return_value = [{"body": "c1", "created_at": "t1"}]
    issue = {"number": 1, "title": "T", "body": "B", "created_at": "t0"}
    buckets = list(pipeline._source_text_buckets_for_issue_like("o", "r", issue))
    where_tags = [w for (w, _txt, _ts) in buckets]
    assert "issue_title" in where_tags and "issue_body" in where_tags and "issue_comment" in where_tags


# ---------------------------------------------------------------------
# find_prs_with_linked_issues
# ---------------------------------------------------------------------
@patch("initial_pipeline.get_commit_detail")
@patch("initial_pipeline.get_pr_commits")
@patch("initial_pipeline.extract_issue_refs_detailed")
def test_find_prs_with_linked_issues_all_paths(
    mock_extract, mock_pr_commits, mock_commit_detail
):
    owner, repo = "o", "r"

    # PR body/title refs + commit message refs + merge commit refs
    pr = {
        "number": 10,
        "title": "Fixes #1",
        "body": "closes o/r#2",
        "merged_at": "now",
        "user": {"login": "pr_author"},
        "html_url": "http://pr",
        "state": "closed",
        "created_at": "t0",
        "merge_commit_sha": "abc123",
    }

    # refs coming from extract_issue_refs_detailed() for 3 places
    def extract_side_effect(text):
        if "Fixes" in text or "closes" in text:
            # PR text path
            return [{"full_repo": None, "number": 2, "has_closing_kw": True}]
        if "merge" in text or "squash" in text:
            return []
        # commit message path
        return [{"full_repo": "o/r", "number": 3, "has_closing_kw": True}]

    mock_extract.side_effect = extract_side_effect

    # PR commits for number=10
    mock_pr_commits.return_value = [
        {"commit": {"message": "Fixes #3"}},
        {"commit": {"message": ""}},
    ]

    # merge commit detail
    mock_commit_detail.return_value = {"commit": {"message": "resolves o/r#4"}}

    # local issues cache hint
    local_issues = [{"number": 2, "user": {"login": "issue2_author"}}]

    out = pipeline.find_prs_with_linked_issues(owner, repo, [pr], local_issues=local_issues)
    assert len(out) == 1
    row = out[0]
    assert row["repo_name"] == "o/r"
    assert row["pr_number"] == 10
    # we aggregate links; ensure both #2 and #3 appear
    all_issue_nums = {link["issue_number"] for link in row["links"]}
    assert {2, 3}.issubset(all_issue_nums)
    # merged flag should propagate
    assert row["merged"] is True


# ---------------------------------------------------------------------
# find_issues_closed_by_repo_commits
# ---------------------------------------------------------------------
@patch("initial_pipeline.get_issue_or_pr_details")
def test_find_issues_closed_by_repo_commits(mock_details):
    mock_details.return_value = {"user": {"login": "issue_author"}}
    commits = [
        {
            "sha": "a1",
            "html_url": "http://c1",
            "author": {"login": "alice"},
            "commit": {"message": "fixes #12 and closes o/r#34"},
        },
        {
            "sha": "a2",
            "html_url": "http://c2",
            "commit": {"author": {"name": "bob"}, "message": "resolve o/r#56"},
        },
        {"sha": "a3", "html_url": "http://c3", "commit": {"message": ""}},
    ]
    out = pipeline.find_issues_closed_by_repo_commits("o", "r", commits)
    nums = {(r["issue_number"], r["commit_sha"]) for r in out}
    assert (12, "a1") in nums and (34, "a1") in nums and (56, "a2") in nums
    assert all(r["has_closing_kw"] and r["would_auto_close"] for r in out)


# ---------------------------------------------------------------------
# find_cross_project_links_issues_and_prs
# ---------------------------------------------------------------------
@patch("initial_pipeline.get_issue_or_pr_details")
@patch("initial_pipeline.get_issue_comments")
def test_find_cross_project_links_issues_and_prs(mock_comments, mock_details):
    # Issue and PR text that reference another repo; ignore same-repo refs
    issues = [{
        "number": 1, "title": "see ext/repo#5", "body": "and o/r#99",
        "created_at": "ti", "html_url": "http://issue/1"
    }]
    prs = [{
        "number": 2, "title": "PR", "body": "mentions ext/repo#7",
        "created_at": "tp", "html_url": "http://pr/2"
    }]
    mock_comments.return_value = [{"body": "also ext/repo#5", "created_at": "tc"}]

    # Target details return once per unique (repo, number)
    def details_side_effect(owner, repo, num):
        if (owner, repo, num) == ("ext", "repo", 5):
            return {"created_at": "t5", "html_url": "http://ext/5", "user": {"login": "u5"}}
        if (owner, repo, num) == ("ext", "repo", 7):
            # mark as PR by including non-empty 'pull_request'
            return {"updated_at": "t7", "html_url": "http://ext/7", "user": {"login": "u7"},
                    "pull_request": {"url": "p"}}
        return {}
    mock_details.side_effect = details_side_effect

    out = pipeline.find_cross_project_links_issues_and_prs("o", "r", issues, prs)
    assert len(out) >= 2  # one for issue→ext#5, one for PR→ext#7
    # Check structure keys exist
    assert {"source", "reference", "target"}.issubset(out[0].keys())
    # Same-repo reference (o/r#99) must be ignored entirely
    all_targets = {(r["target"]["repo_name"], r["target"]["number"]) for r in out}
    assert ("o/r", 99) not in all_targets


# ---------------------------------------------------------------------
# Helpers: ensure_dir, save_json
# ---------------------------------------------------------------------
def test_ensure_dir_and_save_json(tmp_path):
    d = tmp_path / "sub"
    pipeline.ensure_dir(str(d))
    file_path = d / "file.json"
    pipeline.save_json(file_path, {"x": 1})
    with open(file_path) as f:
        assert json.load(f) == {"x": 1}


# ---------------------------------------------------------------------
# Orchestration: process_repo & main
# ---------------------------------------------------------------------
@patch("initial_pipeline.get_repo_meta", return_value={"repo_name": "r"})
@patch("initial_pipeline.get_issues", return_value=[{"id": 1}])
@patch("initial_pipeline.get_pull_requests", return_value=[{"id": 2}])
@patch("initial_pipeline.get_commits", return_value=[{"id": 3}])
@patch("initial_pipeline.find_prs_with_linked_issues", return_value=[{"id": 4}])
@patch("initial_pipeline.find_issues_closed_by_repo_commits", return_value=[{"id": 5}])
@patch("initial_pipeline.find_cross_project_links_issues_and_prs", return_value=[{"id": 6}])
def test_process_repo_runs_all(
    m1, m2, m3, m4, m5, m6, tmp_path, monkeypatch
):
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", str(tmp_path))
    pipeline.process_repo("owner/repo")
    for m in (m1, m2, m3, m4, m5, m6):
        m.assert_called()


def test_main_with_no_repos_exits(monkeypatch):
    monkeypatch.setattr(pipeline, "REPOS", [])
    with pytest.raises(SystemExit):
        pipeline.main([])


@patch("initial_pipeline.process_repo")
def test_main_with_custom_repos_calls_process(mock_proc):
    pipeline.main(["a/b", "c/d"])
    mock_proc.assert_any_call("a/b")
    mock_proc.assert_any_call("c/d")
