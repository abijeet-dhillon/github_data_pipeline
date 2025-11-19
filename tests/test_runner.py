"""Tests for src.pipeline.runner ensuring orchestration flows through dependencies.

Run with:
    pytest tests/test_runner.py --maxfail=1 -v --cov=src.pipeline.runner --cov-report=term-missing
"""

from unittest.mock import patch

import pytest

from src.pipeline import runner


@patch("src.pipeline.runner.save_json")
@patch("src.pipeline.runner.find_cross_project_links_issues_and_prs", return_value=[])
@patch("src.pipeline.runner.find_issues_closed_by_repo_commits", return_value=[])
@patch("src.pipeline.runner.find_prs_with_linked_issues", return_value=[])
@patch("src.pipeline.runner.collect_repo_blame", return_value={"files": []})
@patch("src.pipeline.runner.get_commits", return_value=[{"sha": "abc"}])
@patch("src.pipeline.runner.get_contributors", return_value=[{"id": 3}])
@patch("src.pipeline.runner.get_pull_requests", return_value=[{"id": 2}])
@patch("src.pipeline.runner.get_issues", return_value=[{"id": 1}])
@patch("src.pipeline.runner.get_repo_meta", return_value={"default_branch": "main"})
@patch("src.pipeline.runner.ensure_dir")
def test_process_repo_invokes_all_dependencies(mock_dir, mock_meta, mock_issues, mock_prs,
                                              mock_contribs, mock_commits, mock_blame,
                                              mock_pr_links, mock_closed, mock_cross, mock_save):
    runner.process_repo("owner/repo")
    assert mock_meta.called and mock_issues.called and mock_prs.called
    assert mock_commits.called and mock_blame.called
    # save_json should be called for every output artifact
    assert mock_save.call_count == 9


def test_main_uses_custom_repos(monkeypatch):
    called = []
    monkeypatch.setattr(runner, "process_repo", lambda repo: called.append(repo))
    runner.main(["x/y"])
    assert called == ["x/y"]


def test_main_exits_when_no_repos(monkeypatch):
    monkeypatch.setattr(runner, "process_repo", lambda repo: None)
    monkeypatch.setattr(runner, "REPOS", [])
    with pytest.raises(SystemExit) as excinfo:
        runner.main(None)
    assert excinfo.value.code == 1
