"""Tests for src.retrieval.linkers covering reference extraction and linking.

Run with:
    pytest tests/test_linkers.py --maxfail=1 -v --cov=src.retrieval.linkers --cov-report=term-missing
"""

from unittest.mock import patch

from src.retrieval import linkers


def test_extract_issue_refs_detailed_parses_keywords():
    text = "Fixes #1 and closes other/repo#2!"
    refs = linkers.extract_issue_refs_detailed(text)
    repo_refs = {(ref["full_repo"], ref["number"]) for ref in refs}
    assert (None, 1) in repo_refs and ("other/repo", 2) in repo_refs
    assert any(ref["has_closing_kw"] for ref in refs)


@patch("src.retrieval.linkers.get_issue_or_pr_details", return_value={"user": {"login": "issue-author"}})
@patch("src.retrieval.linkers.get_commit_detail", return_value={"commit": {"message": ""}})
@patch("src.retrieval.linkers.get_pr_commits", return_value=[])
def test_find_prs_with_linked_issues(mock_pr_commits, mock_commit_detail, mock_issue):
    prs = [{
        "number": 7,
        "title": "Fix #12",
        "body": "",
        "user": {"login": "dev"},
        "merged": True,
        "state": "closed",
        "html_url": "url",
    }]
    issues = [{"number": 12, "user": {"login": "issue-author"}}]
    results = linkers.find_prs_with_linked_issues("owner", "repo", prs, issues)
    assert results and results[0]["links"][0]["issue_number"] == 12
    assert results[0]["links"][0]["issue_author"] == "issue-author"


@patch("src.retrieval.linkers.get_issue_or_pr_details", return_value={"user": {"login": "issue-author"}})
@patch("src.retrieval.linkers.get_commit_detail", return_value={"commit": {"message": ""}})
@patch("src.retrieval.linkers.get_pr_commits", return_value=[])
def test_find_prs_with_linked_issues_respects_max(mock_pr_commits, mock_commit_detail, mock_issue):
    prs = [
        {
            "number": 1,
            "title": "Fix #1",
            "body": "",
            "created_at": "2024-01-01T00:00:00Z",
            "user": {"login": "dev1"},
            "merged": False,
            "state": "open",
            "html_url": "url-1",
        },
        {
            "number": 2,
            "title": "Fix #2",
            "body": "",
            "created_at": "2024-02-01T00:00:00Z",
            "user": {"login": "dev2"},
            "merged": False,
            "state": "open",
            "html_url": "url-2",
        },
    ]
    results = linkers.find_prs_with_linked_issues("owner", "repo", prs, [], max_prs=1)
    assert len(results) == 1
    assert results[0]["pr_number"] == 2  # newest PR is scanned first
    assert mock_pr_commits.call_count == 1


@patch("src.retrieval.linkers.get_issue_or_pr_details", return_value={"user": {"login": "issue-author"}})
def test_find_issues_closed_by_repo_commits(mock_issue):
    commits = [{
        "sha": "abc",
        "commit": {"message": "Closes #5", "author": {"name": "dev"}},
        "author": {"login": "dev"},
        "html_url": "commit-url",
    }]
    results = linkers.find_issues_closed_by_repo_commits("o", "r", commits)
    assert results and results[0]["issue_number"] == 5
    assert results[0]["would_auto_close"] is True


@patch("src.retrieval.linkers.get_issue_or_pr_details", return_value={
    "pull_request": {},
    "created_at": "2024-01-01T00:00:00Z",
    "user": {"login": "target"},
    "html_url": "https://github.com/other/repo/issues/1",
})
def test_find_cross_project_links(mock_issue):
    issues = [{
        "number": 9,
        "title": "ref",
        "body": "See other/repo#1",
        "created_at": "2024-01-01T00:00:00Z",
        "html_url": "https://github.com/owner/repo/issues/9",
    }]
    prs = []
    results = linkers.find_cross_project_links_issues_and_prs("owner", "repo", issues, prs)
    assert results and results[0]["target"]["repo_name"] == "other/repo"
