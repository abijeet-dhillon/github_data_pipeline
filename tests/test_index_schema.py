"""Tests for src.indexing.schema ensuring mappings and ID helpers work.

Run with:
    pytest tests/test_index_schema.py --maxfail=1 -v --cov=src.indexing.schema --cov-report=term-missing
"""

from src.indexing import schema


def test_stable_hash_id_is_deterministic():
    doc = {"a": 1, "b": 2}
    assert schema.stable_hash_id(doc) == schema.stable_hash_id({"b": 2, "a": 1})


def test_file_to_index_contains_expected_files():
    keys = set(schema.FILE_TO_INDEX.keys())
    assert "issues.json" in keys
    assert "repo_blame.json" in keys


def test_id_helpers_use_repo_metadata():
    issue = {"repo_name": "o/r", "number": 5}
    assert schema.id_issues(issue) == "o/r#issue#5"

    pr = {"repo_name": "o/r", "number": 7}
    assert schema.id_pull_requests(pr) == "o/r#pr#7"

    blame = {"repo_name": "o/r", "ref": "main"}
    assert schema.id_repo_blame(blame) == "o/r#blame#main"
