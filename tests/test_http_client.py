"""Unit tests for src.retrieval.http_client covering retries and pagination.

Execute with coverage to validate networking helpers:
    pytest tests/test_http_client.py --maxfail=1 -v --cov=src.retrieval.http_client --cov-report=term-missing
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.retrieval import config
from src.retrieval import http_client


def _make_resp(status: int = 200, payload: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    if payload is None:
        payload = {}
    resp.json.return_value = payload
    resp.text = str(payload)
    return resp


def test_sleep_with_jitter(monkeypatch):
    called = {}
    monkeypatch.setattr(http_client.time, "sleep", lambda value: called.setdefault("val", value))
    http_client.sleep_with_jitter(1.5)
    assert isinstance(called["val"], float)


def test_log_http_error_handles_json_and_text(capsys):
    resp = _make_resp(403, {"message": "bad"})
    http_client.log_http_error(resp, "url")
    assert "bad" in capsys.readouterr().out

    resp = _make_resp(429)
    resp.json.side_effect = ValueError()
    resp.text = "plain"
    http_client.log_http_error(resp, "url")
    assert "plain" in capsys.readouterr().out


def test_token_rotation(monkeypatch, capsys):
    original_tokens = config.GITHUB_TOKENS[:]
    original_http_tokens = http_client.GITHUB_TOKENS[:]
    try:
        config.GITHUB_TOKENS[:] = ["t1", "t2"]
        http_client.GITHUB_TOKENS[:] = ["t1", "t2"]
        http_client.GITHUB_TOKEN_INDEX = 0
        http_client.SESSION.headers.pop("Authorization", None)
        http_client.set_auth_header_for_current_token()
        assert http_client.SESSION.headers["Authorization"].endswith("t1")

        assert http_client.switch_to_next_token() is True
        assert http_client.GITHUB_TOKEN_INDEX == 1

        capsys.readouterr()  # clear output buffer
        http_client.switch_to_next_token()
        assert "wrapped" in capsys.readouterr().out

        config.GITHUB_TOKENS[:] = ["solo"]
        http_client.GITHUB_TOKENS[:] = ["solo"]
        http_client.GITHUB_TOKEN_INDEX = 0
        assert http_client.switch_to_next_token() is False
    finally:
        config.GITHUB_TOKENS[:] = original_tokens
        http_client.GITHUB_TOKENS[:] = original_http_tokens


@patch("src.retrieval.http_client.SESSION")
def test_request_success(mock_session):
    mock_session.request.return_value = _make_resp(200, {"ok": 1})
    resp = http_client.request_with_backoff("GET", "https://api.github.com/x")
    assert resp.status_code == 200


@patch("src.retrieval.http_client.sleep_with_jitter", lambda *_: None)
@patch("src.retrieval.http_client.SESSION")
def test_request_retry_on_exception(mock_session):
    mock_session.request.side_effect = [
        requests.RequestException("boom"),
        _make_resp(200, {"ok": 1}),
    ]
    resp = http_client.request_with_backoff("GET", "url")
    assert resp.status_code == 200


@patch("src.retrieval.http_client.sleep_with_jitter", lambda *_: None)
@patch("src.retrieval.http_client.SESSION")
def test_request_rate_limit_switch_token(mock_session):
    config.GITHUB_TOKENS[:] = ["t1", "t2"]
    http_client.GITHUB_TOKEN_INDEX = 0
    r1 = _make_resp(403, {"message": ""}, headers={"X-RateLimit-Remaining": "0"})
    r2 = _make_resp(200, {"ok": True})
    mock_session.request.side_effect = [r1, r2]
    resp = http_client.request_with_backoff("GET", "url")
    assert resp.status_code == 200


@patch("src.retrieval.http_client.sleep_with_jitter", lambda *_: None)
@patch("src.retrieval.http_client.SESSION")
def test_request_retry_after_wait(mock_session):
    r1 = _make_resp(403, {"message": ""}, headers={"Retry-After": "1"})
    r2 = _make_resp(200, {"ok": True})
    mock_session.request.side_effect = [r1, r2]
    resp = http_client.request_with_backoff("GET", "url")
    assert resp.status_code == 200


@patch("src.retrieval.http_client.request_with_backoff")
def test_paged_get_sets_repo_name_and_stops_without_link(mock_request, monkeypatch):
    monkeypatch.setattr(config, "PER_PAGE", 2)
    monkeypatch.setattr(http_client, "PER_PAGE", 2)
    mock_request.side_effect = [_make_resp(200, [{"id": 1}, {"id": 2}])]
    results = http_client.paged_get("url", "o", "r")
    assert [entry["repo_name"] for entry in results] == ["o/r", "o/r"]
    assert mock_request.call_count == 1


@patch("src.retrieval.http_client.requests.post")
def test_run_graphql_query_success(mock_post):
    mock_post.return_value = _make_resp(200, {"data": {"ok": True}})
    result = http_client.run_graphql_query("query", {})
    assert result == {"ok": True}


@patch("src.retrieval.http_client.requests.post")
def test_run_graphql_query_handles_401(mock_post, monkeypatch):
    mock_post.side_effect = [_make_resp(401, {}), _make_resp(200, {"data": {"ok": True}})]
    original = http_client.GITHUB_TOKENS[:]
    try:
        monkeypatch.setattr(http_client, "GITHUB_TOKENS", ["a", "b"], raising=False)
        http_client.GITHUB_TOKEN_INDEX = 0
        result = http_client.run_graphql_query("query", {})
        assert result == {"ok": True}
    finally:
        http_client.GITHUB_TOKENS[:] = original


@patch("src.retrieval.http_client.sleep_on_rate_limit")
@patch("src.retrieval.http_client.sleep_with_jitter", lambda *_: None)
@patch("src.retrieval.http_client.requests.post")
def test_run_graphql_query_handles_rate_limit(mock_post, mock_sleep, monkeypatch):
    headers = {"X-RateLimit-Remaining": "0"}
    mock_post.side_effect = [
        _make_resp(403, {}, headers=headers),
        _make_resp(403, {}, headers=headers),
        _make_resp(200, {"data": {"ok": True}}),
    ]
    original = http_client.GITHUB_TOKENS[:]
    try:
        monkeypatch.setattr(http_client, "GITHUB_TOKENS", ["a", "b"], raising=False)
        http_client.GITHUB_TOKEN_INDEX = 0
        result = http_client.run_graphql_query("query", {})
        assert result == {"ok": True}
        assert mock_sleep.called
    finally:
        http_client.GITHUB_TOKENS[:] = original


@patch("src.retrieval.http_client.log_http_error")
@patch("src.retrieval.http_client.SESSION")
def test_request_terminal_error_returns_resp(mock_session, mock_log):
    resp = _make_resp(404, {})
    mock_session.request.return_value = resp
    result = http_client.request_with_backoff("GET", "url")
    assert result is resp
    mock_log.assert_called_once()


@patch("src.retrieval.http_client.request_with_backoff")
def test_paged_get_accumulates_pages_via_link_header(mock_request, monkeypatch):
    monkeypatch.setattr(config, "PER_PAGE", 2)
    monkeypatch.setattr(http_client, "PER_PAGE", 2)
    mock_request.side_effect = [
        _make_resp(
            200,
            [{"id": 1}, {"id": 2}],
            headers={"Link": '<https://api.github.com/x?per_page=2&after=c1>; rel="next"'},
        ),
        _make_resp(200, [{"id": 3}], headers={}),
    ]
    results = http_client.paged_get("https://api.github.com/x", "o", "r")
    assert [entry["id"] for entry in results] == [1, 2, 3]
    called_urls = [call.args[1] for call in mock_request.call_args_list]
    assert called_urls[0] == "https://api.github.com/x?per_page=2"
    assert called_urls[1] == "https://api.github.com/x?per_page=2&after=c1"
