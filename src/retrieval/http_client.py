"""HTTP and GraphQL helpers with retry/backoff logic for the retrieval workflow."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

from .config import (
    BACKOFF_BASE_SEC,
    GITHUB_TOKENS,
    GRAPHQL_URL,
    MAX_RETRIES,
    MAX_WAIT_ON_403,
    PER_PAGE,
    RATE_LIMIT_TOKEN_RESET_WAIT_SEC,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": USER_AGENT,
    }
)

GITHUB_TOKEN_INDEX = 0


def sleep_with_jitter(base: float) -> None:
    """Pause execution with +/- 25% jitter to avoid synchronized retries."""
    jitter = base * 0.25 * (0.5 - (os.urandom(1)[0] / 255.0))
    time.sleep(max(0.0, base + jitter))


def sleep_on_rate_limit(reason: str) -> None:
    """Sleep for the configured interval when every token is still rate limited."""
    wait_sec = max(0, RATE_LIMIT_TOKEN_RESET_WAIT_SEC)
    if wait_sec <= 0:
        return
    print(f"[rate-limit] {reason}; sleeping {wait_sec}s")
    time.sleep(wait_sec)


def log_http_error(resp: requests.Response, url: str) -> None:
    """Print a short, human-readable message when GitHub returns an error."""
    try:
        body = resp.json()
    except Exception:
        body = {"text": (resp.text or "")[:300]}
    msg = body.get("message") or body.get("error") or body.get("text")
    print(f"[error] HTTP {resp.status_code} for {url}\n  -> {msg}")


def get_current_token() -> Optional[str]:
    """Return the token for the current index or None when exhausted."""
    try:
        token = GITHUB_TOKENS[GITHUB_TOKEN_INDEX]
    except Exception:
        token = None
    return token or None


def set_auth_header_for_current_token() -> None:
    """Set or clear SESSION Authorization header for the current token index."""
    token = get_current_token()
    if token:
        SESSION.headers["Authorization"] = f"token {token}"
    else:
        SESSION.headers.pop("Authorization", None)


def switch_to_next_token() -> bool:
    """Advance to the next token if available; return True if switched."""
    global GITHUB_TOKEN_INDEX
    if not GITHUB_TOKENS or len(GITHUB_TOKENS) == 1:
        return False

    last_index = len(GITHUB_TOKENS) - 1
    GITHUB_TOKEN_INDEX = (GITHUB_TOKEN_INDEX + 1) % len(GITHUB_TOKENS)
    set_auth_header_for_current_token()

    if GITHUB_TOKEN_INDEX == 0 and last_index > 0:
        print(f"[rate-limit] wrapped to token 1/{len(GITHUB_TOKENS)}")
    else:
        print(f"[rate-limit] switched to token {GITHUB_TOKEN_INDEX + 1}/{len(GITHUB_TOKENS)}")
    return True


def graphql_headers() -> Dict[str, str]:
    """Build headers for GraphQL requests, attaching the active PAT if available."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    token = get_current_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def run_graphql_query(query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a GraphQL query with retry/backoff semantics similar to REST."""
    payload = {"query": query, "variables": variables}
    last_exc = None
    rotated_due_to_rate_limit = False
    wrapped_on_last_rotation = False

    for attempt in range(1, MAX_RETRIES + 1):
        headers = graphql_headers()
        try:
            resp = requests.post(
                GRAPHQL_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            last_exc = exc
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[graphql retry {attempt}/{MAX_RETRIES}] {exc} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
            print("    done sleeping, resuming retrieval run...")
            continue

        if resp.status_code == 200:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            data = resp.json()
            if data.get("errors"):
                messages = ", ".join(
                    [str(err.get("message")) for err in data["errors"] if isinstance(err, dict)]
                )
                raise RuntimeError(f"GraphQL error: {messages or data['errors']}")
            return data.get("data") or {}

        if resp.status_code == 401:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            if switch_to_next_token():
                continue
            log_http_error(resp, GRAPHQL_URL)
            break

        if resp.status_code in (403, 429):
            headers_resp = resp.headers or {}
            remaining = headers_resp.get("X-RateLimit-Remaining")
            reset = headers_resp.get("X-RateLimit-Reset")
            retry_after = headers_resp.get("Retry-After")
            is_rate_limited = (remaining == "0") or (reset and str(reset).isdigit())
            if is_rate_limited:
                token_count = len(GITHUB_TOKENS)
                reached_end_of_rotation = rotated_due_to_rate_limit and (
                    wrapped_on_last_rotation or (token_count > 0 and GITHUB_TOKEN_INDEX == (token_count - 1))
                )
                if token_count <= 1:
                    reason = "GraphQL rate limit persists with a single token"
                    sleep_on_rate_limit(reason)
                    print("  done sleeping, resuming retrieval run...")
                    rotated_due_to_rate_limit = False
                    wrapped_on_last_rotation = False
                    continue
                if reached_end_of_rotation:
                    reason = "GraphQL rate limit persists after cycling through all tokens"
                    sleep_on_rate_limit(reason)
                    print("  done sleeping, resuming retrieval run...")
                    rotated_due_to_rate_limit = False
                    wrapped_on_last_rotation = False
                    continue

                prev_index = GITHUB_TOKEN_INDEX
                if switch_to_next_token():
                    wrapped_on_last_rotation = token_count > 0 and prev_index == (token_count - 1)
                    rotated_due_to_rate_limit = True
                    continue

            if retry_after and str(retry_after).isdigit():
                wait_sec = int(retry_after)
            elif reset and str(reset).isdigit():
                wait_sec = max(0, int(reset) - int(time.time())) + 1
            else:
                wait_sec = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            wait_sec = min(wait_sec, MAX_WAIT_ON_403)
            print(f"[graphql backoff {resp.status_code}] waiting {wait_sec}s for {GRAPHQL_URL}")
            sleep_with_jitter(wait_sec)
            print("  done sleeping, resuming retrieval run...")
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        if resp.status_code in {400, 404, 410, 422}:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            log_http_error(resp, GRAPHQL_URL)
            break

        if attempt < MAX_RETRIES:
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(
                f"[graphql retry {attempt}/{MAX_RETRIES}] HTTP {resp.status_code} -> sleep {delay:.1f}s"
            )
            sleep_with_jitter(delay)
            print("  done sleeping, resuming retrieval run...")
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        log_http_error(resp, GRAPHQL_URL)
        rotated_due_to_rate_limit = False
        wrapped_on_last_rotation = False
        break

    if last_exc:
        raise last_exc
    raise RuntimeError("GraphQL request failed after retries.")


def request_with_backoff(method: str, url: str, **kwargs) -> requests.Response:
    """Perform a REST call with retry, exponential backoff, and token cycling."""
    if "Authorization" not in getattr(SESSION, "headers", {}):
        set_auth_header_for_current_token()

    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
    last_exc = None
    terminal_errors = {400, 404, 410, 422}
    rotated_due_to_rate_limit = False
    wrapped_on_last_rotation = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = SESSION.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[retry {attempt}/{MAX_RETRIES}] {exc} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
            print("  done sleeping, resuming retrieval run...")
            last_exc = exc
            continue

        if 200 <= resp.status_code < 300:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            return resp

        if resp.status_code == 401:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            if switch_to_next_token():
                continue
            log_http_error(resp, url)
            return resp

        if resp.status_code in (403, 429):
            headers_resp = resp.headers or {}
            remaining = headers_resp.get("X-RateLimit-Remaining")
            reset = headers_resp.get("X-RateLimit-Reset")
            retry_after = headers_resp.get("Retry-After")
            is_rate_limited = (remaining == "0") or (reset and str(reset).isdigit())
            has_retry_after = retry_after and str(retry_after).isdigit()

            if is_rate_limited:
                token_count = len(GITHUB_TOKENS)
                reached_end_of_rotation = rotated_due_to_rate_limit and (
                    wrapped_on_last_rotation or (token_count > 0 and GITHUB_TOKEN_INDEX == (token_count - 1))
                )
                if token_count <= 1:
                    reason = "rate limit persists with a single token"
                    sleep_on_rate_limit(reason)
                    print("  done sleeping, resuming retrieval run...")
                    rotated_due_to_rate_limit = False
                    wrapped_on_last_rotation = False
                    continue
                if reached_end_of_rotation:
                    reason = "rate limit persists after cycling through all tokens"
                    sleep_on_rate_limit(reason)
                    print("  done sleeping, resuming retrieval run...")
                    rotated_due_to_rate_limit = False
                    wrapped_on_last_rotation = False
                    continue

                prev_index = GITHUB_TOKEN_INDEX
                if switch_to_next_token():
                    wrapped_on_last_rotation = token_count > 0 and prev_index == (token_count - 1)
                    rotated_due_to_rate_limit = True
                    continue

            if has_retry_after:
                wait_sec = int(retry_after)
            elif reset and str(reset).isdigit():
                wait_sec = max(0, int(reset) - int(time.time())) + 1
            else:
                wait_sec = BACKOFF_BASE_SEC * (2 ** (attempt - 1))

            wait_sec = min(wait_sec, MAX_WAIT_ON_403)
            print(f"[backoff {resp.status_code}] waiting {wait_sec}s for {url}")
            sleep_with_jitter(wait_sec)
            print("  done sleeping, resuming retrieval run...")
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        if resp.status_code in terminal_errors:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            log_http_error(resp, url)
            return resp

        if attempt < MAX_RETRIES:
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[retry {attempt}/{MAX_RETRIES}] HTTP {resp.status_code} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
            print("  done sleeping, resuming retrieval run...")
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        rotated_due_to_rate_limit = False
        wrapped_on_last_rotation = False
        return resp

    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed after retries.")


def paged_get(url: str, owner: str, repo: str, *, max_pages: int = 0) -> List[Dict[str, Any]]:
    """Automatically retrieve pages until the API returns empty results or max_pages hits."""
    results: List[Dict[str, Any]] = []
    page = 1
    while True:
        if max_pages and page > max_pages:
            break
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}per_page={PER_PAGE}&page={page}"
        resp = request_with_backoff("GET", page_url)
        if resp.status_code != 200:
            try:
                err = resp.json().get("message")
            except Exception:
                err = (resp.text or "")[:200]
            print(f"[warn] {page_url} → {resp.status_code} :: {err}")
            break

        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break

        for entry in batch:
            entry["repo_name"] = f"{owner}/{repo}"
        results.extend(batch)

        if len(batch) < PER_PAGE:
            break

        page += 1
    return results


__all__ = [
    "SESSION",
    "sleep_with_jitter",
    "sleep_on_rate_limit",
    "log_http_error",
    "get_current_token",
    "set_auth_header_for_current_token",
    "switch_to_next_token",
    "graphql_headers",
    "run_graphql_query",
    "request_with_backoff",
    "paged_get",
]
