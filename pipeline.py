"""
pipeline.py
----------------
A unified GitHub data pipeline that automates the retrieval, parsing, and linking of
repository data using the GitHub REST API (v3).

Functionality:
    • Collects repository metadata, issues, pull requests, commits, and comments.
    • Extracts and links issues mentioned in PRs, commits, and merge messages.
    • Identifies cross-repository references (e.g., org/repo#123) across issues and PRs.
    • Handles rate-limit backoff, token rotation, and request retries for reliability.
    • Outputs structured JSON datasets for downstream indexing or analysis.

Workflow:
    1. Fetches and normalizes data for each repository in `REPOS`.
    2. Writes per-repository JSON outputs into `./output/{owner_repo}/`.
    3. Each file (e.g., `issues.json`, `commits.json`) represents a unified data view
       for that repository, suitable for ingestion into Elasticsearch.

Usage:
    - Configure GitHub API tokens at the top of this file.
    - Add or modify repositories in the `REPOS` list.
    - Run:
          python3 pipeline.py
    - Optionally provide repository names as CLI arguments:
          python3 pipeline.py owner/repo another/repo

Outputs (per repository):
    output/{owner_repo}/
        ├── repo_meta.json
        ├── issues.json
        ├── pull_requests.json
        ├── commits.json
        ├── contributors.json
        ├── prs_with_linked_issues.json
        ├── issues_closed_by_commits.json
        └── cross_repo_links.json
"""


import os
import re
import json
import sys
import time
import datetime as dt
import requests
from collections import Counter, defaultdict
from typing import Dict, Any, List, Tuple, Optional, Set
from urllib.parse import quote_plus


# --- configuration ---
GITHUB_TOKENS      = ["", ""]     
GITHUB_TOKEN_INDEX = 0
USER_AGENT         = "cosc448-initial-pipeline/1.0 (+abijeet)"
BASE_URL           = "https://api.github.com"
PER_PAGE           = 100
REQUEST_TIMEOUT    = 90
MAX_RETRIES        = max(6, len(GITHUB_TOKENS) * 2) 
BACKOFF_BASE_SEC   = 2
OUTPUT_DIR         = "./output"
MAX_PAGES_COMMITS  = int(os.getenv("MAX_PAGES_COMMITS", "0"))  # 0 = no cap
MAX_WAIT_ON_403    = int(os.getenv("MAX_WAIT_ON_403", "180"))
RATE_LIMIT_TOKEN_RESET_WAIT_SEC = int(
    os.getenv("RATE_LIMIT_TOKEN_RESET_WAIT_SEC", str(60 * 60))
)
INCREMENTAL_LOOKBACK_SEC = int(os.getenv("INCREMENTAL_LOOKBACK_SEC", "300"))
ISSUE_DETAIL_CACHE = {}
COMMIT_CACHE       = {}
GRAPHQL_URL        = "https://api.github.com/graphql"
BLAME_EXAMPLE_LIMIT = int(os.getenv("BLAME_EXAMPLE_LIMIT", "5"))
BLAME_FILE_LIMIT = int(os.getenv("BLAME_FILE_LIMIT", "0"))  # 0 = no limit
REPOS              = [
    # "micromatch/micromatch",
    # "laravel-mix/laravel-mix",
    # "standard/standard",
    # "istanbuljs/nyc",
    # "axios/axios",
    # "rollup/rollup",
    "numpy/numpy",
    "flutter/flutter",
    "apache/spark",
    "reduxjs/redux",
    "torvalds/linux",
    "grafana/grafana",
    "django/django",
    "prettier/prettier",
    "pandas-dev/pandas"
]


# --- https setup ---
SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": USER_AGENT,
})
if GITHUB_TOKENS and GITHUB_TOKENS[0]:
    SESSION.headers["Authorization"] = f"token {GITHUB_TOKENS[0]}"


# --- helpers ---
def sleep_with_jitter(base: float) -> None:
    """Pause execution with +/- 25% jitter to avoid synchronized retries."""
    jitter = base * 0.25 * (0.5 - (os.urandom(1)[0] / 255.0))
    time.sleep(max(0.0, base + jitter))


def _sleep_on_rate_limit(reason: str) -> None:
    """Sleep for a configured interval when every token is still rate limited."""
    wait_sec = max(0, RATE_LIMIT_TOKEN_RESET_WAIT_SEC)
    if wait_sec <= 0:
        return
    print(f"[rate-limit] {reason}; sleeping {wait_sec}s")
    time.sleep(wait_sec)


def _log_http_error(resp: requests.Response, url: str) -> None:
    """Print a short, human-readable message when GitHub returns an error."""
    try:
        body = resp.json()
    except Exception:
        body = {"text": (resp.text or "")[:300]}
    msg = body.get("message") or body.get("error") or body.get("text")
    print(f"[error] HTTP {resp.status_code} for {url}\n  -> {msg}")


def _get_current_token() -> Optional[str]:
    """Return the token for the current index or None when exhausted."""
    try:
        token = GITHUB_TOKENS[GITHUB_TOKEN_INDEX]
    except Exception:
        token = None
    return token or None


def _set_auth_header_for_current_token() -> None:
    """Set or clear SESSION Authorization header for the current token index."""
    token = _get_current_token()
    if token:
        SESSION.headers["Authorization"] = f"token {token}"
    else:
        SESSION.headers.pop("Authorization", None)


def _switch_to_next_token() -> bool:
    """Advance to the next token if available; return True if switched."""
    global GITHUB_TOKEN_INDEX
    if not GITHUB_TOKENS or len(GITHUB_TOKENS) == 1:
        return False

    last_index = len(GITHUB_TOKENS) - 1
    GITHUB_TOKEN_INDEX = (GITHUB_TOKEN_INDEX + 1) % len(GITHUB_TOKENS)
    _set_auth_header_for_current_token()

    if GITHUB_TOKEN_INDEX == 0 and last_index > 0:
        print(f"[rate-limit] wrapped to token 1/{len(GITHUB_TOKENS)}")
    else:
        print(f"[rate-limit] switched to token {GITHUB_TOKEN_INDEX + 1}/{len(GITHUB_TOKENS)}")
    return True


def ensure_dir(p: str) -> None:
    """Create output directories as-needed without raising for existing folders."""
    os.makedirs(p, exist_ok=True)


def save_json(path: str, data: Any) -> None:
    """Write JSON to disk using UTF-8 and deterministic formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --- graphql helpers / git blame ---
BLAME_QUERY_BY_REF = """
query BlameByRef($owner:String!, $name:String!, $qualified:String!, $path:String!) {
  repository(owner:$owner, name:$name) {
    ref(qualifiedName:$qualified) {
      name
      target {
        __typename
        ... on Commit {
          oid
          blame(path:$path) {
            ranges {
              startingLine
              endingLine
              age
              commit {
                oid
                committedDate
                message
                author {
                  name
                  email
                  user { login }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

BLAME_QUERY_BY_OBJECT = """
query BlameByObject($owner:String!, $name:String!, $ref:String!, $path:String!) {
  repository(owner:$owner, name:$name) {
    object(expression:$ref) {
      __typename
      ... on Commit {
        oid
        blame(path:$path) {
          ranges {
            startingLine
            endingLine
            age
            commit {
              oid
              committedDate
              message
              author {
                name
                email
                user { login }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _graphql_headers() -> Dict[str, str]:
    """Build headers for GraphQL requests, attaching the active PAT if available."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    token = _get_current_token()
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
        headers = _graphql_headers()
        try:
            resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[graphql retry {attempt}/{MAX_RETRIES}] {exc} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
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
            if _switch_to_next_token():
                continue
            _log_http_error(resp, GRAPHQL_URL)
            break

        if resp.status_code in (403, 429):
            headers_resp = resp.headers or {}
            remaining = headers_resp.get("X-RateLimit-Remaining")
            reset = headers_resp.get("X-RateLimit-Reset")
            retry_after = headers_resp.get("Retry-After")
            is_rate_limited = (remaining == "0") or (reset and str(reset).isdigit())
            if is_rate_limited:
                if rotated_due_to_rate_limit:
                    reason = "GraphQL rate limit persists after cycling tokens"
                    if wrapped_on_last_rotation:
                        reason = "GraphQL rate limit persists after cycling through all tokens"
                    _sleep_on_rate_limit(reason)
                    rotated_due_to_rate_limit = False
                    wrapped_on_last_rotation = False
                    continue

                prev_index = GITHUB_TOKEN_INDEX
                if _switch_to_next_token():
                    token_count = len(GITHUB_TOKENS)
                    wrapped_on_last_rotation = (
                        token_count > 0 and prev_index == (token_count - 1)
                    )
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
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        if resp.status_code in {400, 404, 410, 422}:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            _log_http_error(resp, GRAPHQL_URL)
            break

        if attempt < MAX_RETRIES:
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[graphql retry {attempt}/{MAX_RETRIES}] HTTP {resp.status_code} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        _log_http_error(resp, GRAPHQL_URL)
        rotated_due_to_rate_limit = False
        wrapped_on_last_rotation = False
        break

    if last_exc:
        raise last_exc
    raise RuntimeError("GraphQL request failed after retries.")


def author_key_from_commit_author(author_obj: Optional[dict]) -> str:
    """Normalize commit author identity, preferring login > name > email."""
    author_obj = author_obj or {}
    login = ((author_obj.get("user") or {}).get("login")) or ""
    name = author_obj.get("name") or ""
    email = author_obj.get("email") or ""
    return login or name or email or "unknown"


def one_line(msg: Optional[str]) -> str:
    """Return the first line of a commit or blame message."""
    if not msg:
        return ""
    return msg.splitlines()[0].strip()


def _lookup_commit_for_blame(commit_lookup: Dict[str, dict],
                             owner: str,
                             repo: str,
                             sha: Optional[str]) -> Optional[dict]:
    """Pull commit metadata for blame ranges, caching files_changed details."""
    if not sha:
        return None
    if sha in commit_lookup and commit_lookup[sha]:
        return commit_lookup[sha]

    detail = get_commit_detail(owner, repo, sha)
    if not detail:
        return None
    detail = detail.copy()
    files = detail.get("files") or []
    detail["files_changed"] = [f.get("filename") for f in files if f.get("filename")]
    detail["files_changed_count"] = len(detail["files_changed"])
    detail.setdefault("repo_name", f"{owner}/{repo}")
    detail.setdefault("sha", sha)
    commit_lookup[sha] = detail
    return detail


def summarize_blame_ranges(blame_ranges: List[Dict[str, Any]],
                           commit_lookup: Dict[str, dict],
                           owner: str,
                           repo: str) -> Dict[str, Any]:
    """Aggregate blame ranges into author summaries and worked examples."""
    total_lines = 0
    lines_by_author: Counter = Counter()
    ranges_by_author: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    examples: List[Dict[str, Any]] = []

    for rg in blame_ranges:
        start = int(rg.get("startingLine") or 0)
        end = int(rg.get("endingLine") or start)
        count = max(0, end - start + 1)
        total_lines += count

        commit_obj = rg.get("commit") or {}
        author = author_key_from_commit_author(commit_obj.get("author"))
        commit_sha = commit_obj.get("oid")
        lines_by_author[author] += count

        matching_commit = _lookup_commit_for_blame(commit_lookup, owner, repo, commit_sha)
        files_changed = (matching_commit or {}).get("files_changed") or []
        match_summary = None
        if matching_commit:
            match_summary = {
                "repo_name": matching_commit.get("repo_name") or f"{owner}/{repo}",
                "sha": matching_commit.get("sha") or commit_sha,
                "html_url": matching_commit.get("html_url"),
                "author_login": ((matching_commit.get("author") or {}).get("login")),
                "commit_author": ((matching_commit.get("commit") or {}).get("author")),
                "files_changed": files_changed,
                "files_changed_count": matching_commit.get("files_changed_count", len(files_changed)),
            }

        range_entry = {
            "start": start,
            "end": end,
            "count": count,
            "age": rg.get("age"),
            "commit_sha": commit_sha,
            "committed_date": commit_obj.get("committedDate"),
            "message": one_line(commit_obj.get("message")),
            "matching_commit": match_summary,
        }
        ranges_by_author[author].append(range_entry)

        if len(examples) < BLAME_EXAMPLE_LIMIT:
            examples.append({
                "lines": {"start": start, "end": end, "count": count},
                "commit_sha": commit_sha,
                "committed_date": commit_obj.get("committedDate"),
                "who": author,
                "message": range_entry["message"],
                "matching_commit": match_summary,
            })

    authors_sorted = sorted(lines_by_author.items(), key=lambda kv: kv[1], reverse=True)
    authors_detail = [
        {
            "author": author,
            "total_lines": total,
            "ranges": ranges_by_author[author],
        }
        for author, total in authors_sorted
    ]

    return {
        "total_lines": total_lines,
        "ranges_count": len(blame_ranges),
        "authors": authors_detail,
        "examples": examples,
    }


def list_repo_files(owner: str, repo: str, branch: str) -> List[str]:
    """Return all blob paths for a branch using the git tree API (recursive)."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    resp = _request("GET", url)
    if resp.status_code != 200:
        _log_http_error(resp, url)
        return []

    payload = resp.json() or {}
    tree_entries = payload.get("tree") or []
    files = [
        entry.get("path")
        for entry in tree_entries
        if entry.get("type") == "blob" and entry.get("path")
    ]
    if payload.get("truncated"):
        print(f"[warn] file tree truncated for {owner}/{repo}@{branch}; returned {len(files)} files")
    return files


def fetch_file_blame(owner: str,
                     repo: str,
                     branch: str,
                     file_path: str) -> Dict[str, Any]:
    """Request blame ranges for a file, falling back between ref/object queries."""
    qualified = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
    blame_ranges: List[Dict[str, Any]] = []
    root_commit_oid = None

    try:
        data = run_graphql_query(BLAME_QUERY_BY_REF, {
            "owner": owner,
            "name": repo,
            "qualified": qualified,
            "path": file_path,
        })
        target = (((data.get("repository") or {}).get("ref") or {}).get("target") or {})
        if target.get("__typename") != "Commit":
            raise RuntimeError(f"Ref target type {target.get('__typename')} for {file_path}")
        root_commit_oid = target.get("oid")
        blame_ranges = (((target.get("blame") or {}).get("ranges")) or [])
    except Exception as exc:
        print(f"[warn] GraphQL ref blame fallback for {owner}/{repo}:{file_path} -> {exc}")
        data = run_graphql_query(BLAME_QUERY_BY_OBJECT, {
            "owner": owner,
            "name": repo,
            "ref": branch,
            "path": file_path,
        })
        obj = ((data.get("repository") or {}).get("object") or {})
        if obj.get("__typename") != "Commit":
            raise RuntimeError(f"Object type {obj.get('__typename')} for {file_path}")
        root_commit_oid = obj.get("oid")
        blame_ranges = (((obj.get("blame") or {}).get("ranges")) or [])

    return {
        "ranges": blame_ranges,
        "root_commit_oid": root_commit_oid,
    }


def collect_repo_blame(owner: str,
                       repo: str,
                       repo_meta: Dict[str, Any],
                       commits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Retrieve blame slices for repo files and enrich with commit summaries."""
    repo_full = f"{owner}/{repo}"
    default_branch = (repo_meta or {}).get("default_branch") or "main"
    if not default_branch:
        default_branch = "main"

    has_graphql_token = any(t for t in GITHUB_TOKENS if t)
    generated_at = (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    if not has_graphql_token:
        print("[warn] skipping GraphQL blame retrieval - no GitHub tokens configured.")
        return {
            "repo_name": repo_full,
            "ref": default_branch,
            "files": [],
            "generated_at": generated_at,
            "error": "GitHub token required for GraphQL blame queries",
        }

    cached_doc = _load_cached_dict(owner, repo, "repo_blame.json")
    cached_head = _cached_blame_head_sha(cached_doc)
    current_head = next((c.get("sha") for c in commits if c.get("sha")), None)

    if cached_doc and cached_head and current_head and cached_head == current_head:
        cached_doc["generated_at"] = generated_at
        cached_doc["head_commit_sha"] = current_head
        return cached_doc

    repo_files = list_repo_files(owner, repo, default_branch)
    if not repo_files:
        print(f"[warn] unable to enumerate files for {repo_full}@{default_branch}")
        return {
            "repo_name": repo_full,
            "ref": default_branch,
            "files": [],
            "generated_at": generated_at,
            "error": "Failed to list repository files",
        }

    if BLAME_FILE_LIMIT > 0 and len(repo_files) > BLAME_FILE_LIMIT:
        repo_files = repo_files[:BLAME_FILE_LIMIT]
        print(f"[info] limiting blame files for {repo_full} to first {BLAME_FILE_LIMIT} entries")

    desired_files = repo_files
    existing_files = {
        entry.get("path"): entry
        for entry in (cached_doc.get("files") or [])
        if entry.get("path")
    }
    for path in list(existing_files.keys()):
        if path not in desired_files:
            existing_files.pop(path, None)

    needs_refresh: Set[str] = {path for path in desired_files if path not in existing_files}
    if cached_doc and cached_head and current_head and cached_head != current_head:
        changed = _get_changed_files_between_refs(owner, repo, cached_head, current_head)
        if changed is None:
            needs_refresh = set(desired_files)
        else:
            for info in changed:
                path = info.get("path")
                prev = info.get("previous")
                status = (info.get("status") or "").lower()
                if status == "removed":
                    if path:
                        existing_files.pop(path, None)
                    if prev:
                        existing_files.pop(prev, None)
                    continue
                if prev and prev != path:
                    existing_files.pop(prev, None)
                if path and path in desired_files:
                    needs_refresh.add(path)

    refresh_paths = [path for path in desired_files if path in needs_refresh]
    existing_count_matches = len(existing_files) == len(desired_files)
    if not refresh_paths and existing_files and existing_count_matches:
        return {
            "repo_name": repo_full,
            "ref": default_branch,
            "files": [existing_files[path] for path in desired_files if path in existing_files],
            "generated_at": generated_at,
            "head_commit_sha": current_head or cached_head,
        }

    commit_lookup = {
        c.get("sha"): c
        for c in commits
        if c.get("sha")
    }

    files_doc: List[Dict[str, Any]] = []
    processed = 0
    for file_path in refresh_paths:
        try:
            blame_payload = fetch_file_blame(owner, repo, default_branch, file_path)
        except Exception as exc:
            print(f"[warn] blame failed for {repo_full}:{file_path} -> {exc}")
            continue

        ranges = blame_payload.get("ranges") or []
        if not ranges:
            print(f"[warn] blame empty for {repo_full}:{file_path}")
            continue

        summary = summarize_blame_ranges(ranges, commit_lookup, owner, repo)
        existing_files[file_path] = {
            "path": file_path,
            "ref": default_branch,
            "root_commit_oid": blame_payload.get("root_commit_oid"),
            "ranges_count": summary["ranges_count"],
            "total_lines": summary["total_lines"],
            "authors": summary["authors"],
            "examples": summary["examples"],
        }
        processed += 1
        if processed % 50 == 0:
            print(f"    processed blame for {processed} updated files in {repo_full}...")

    for path in desired_files:
        if path in existing_files:
            files_doc.append(existing_files[path])

    return {
        "repo_name": repo_full,
        "ref": default_branch,
        "files": files_doc,
        "generated_at": generated_at,
        "head_commit_sha": current_head or cached_head,
    }


# --- http request ---
def _request(method: str, url: str, **kwargs) -> requests.Response:
    """Perform a REST call with retry, exponential backoff, and token cycling."""
    if "Authorization" not in getattr(SESSION, "headers", {}):
        _set_auth_header_for_current_token()

    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
    last_exc = None
    TERMINAL_4XX = {400, 404, 410, 422}
    rotated_due_to_rate_limit = False
    wrapped_on_last_rotation = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = SESSION.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[retry {attempt}/{MAX_RETRIES}] {e} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
            last_exc = e
            continue

        if 200 <= resp.status_code < 300:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            return resp

        if resp.status_code == 401:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            if _switch_to_next_token():
                continue
            _log_http_error(resp, url)
            return resp

        if resp.status_code in (403, 429):
            # Treat rate-limit/abuse responses uniformly and decide whether to rotate tokens or wait.
            headers = resp.headers or {}
            remaining = headers.get("X-RateLimit-Remaining")
            reset = headers.get("X-RateLimit-Reset")
            retry_after = headers.get("Retry-After")
            is_rate_limited = (remaining == "0") or (reset and str(reset).isdigit())
            has_retry_after = retry_after and str(retry_after).isdigit()

            if is_rate_limited:
                if rotated_due_to_rate_limit:
                    reason = "rate limit persists after cycling tokens"
                    if wrapped_on_last_rotation:
                        reason = "rate limit persists after cycling through all tokens"
                    _sleep_on_rate_limit(reason)
                    rotated_due_to_rate_limit = False
                    wrapped_on_last_rotation = False
                    continue

                prev_index = GITHUB_TOKEN_INDEX
                if _switch_to_next_token():
                    token_count = len(GITHUB_TOKENS)
                    wrapped_on_last_rotation = (
                        token_count > 0 and prev_index == (token_count - 1)
                    )
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
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        if resp.status_code in TERMINAL_4XX:
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            _log_http_error(resp, url)
            return resp

        if attempt < MAX_RETRIES:
            delay = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[retry {attempt}/{MAX_RETRIES}] HTTP {resp.status_code} -> sleep {delay:.1f}s")
            sleep_with_jitter(delay)
            rotated_due_to_rate_limit = False
            wrapped_on_last_rotation = False
            continue

        rotated_due_to_rate_limit = False
        wrapped_on_last_rotation = False
        return resp

    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed after retries.")


# --- get info for url ---
def _paged_get(url: str, owner: str, repo: str, *, max_pages: int = 0) -> List[Dict[str, Any]]:
    """Automatically retrieve all pages until API returns empty results (or max_pages is hit)."""
    results: List[Dict[str, Any]] = []
    page = 1
    while True:
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}per_page={PER_PAGE}&page={page}"
        resp = _request("GET", page_url)
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
        if max_pages and page >= max_pages:
            print(f"[info] hit max_pages={max_pages} on {url}")
            break
        page += 1
    return results


# --- cached dataset helpers ---
def _repo_cache_dir(owner: str, repo: str) -> str:
    return os.path.join(OUTPUT_DIR, f"{owner}_{repo}")


def _cache_file_path(owner: str, repo: str, filename: str) -> str:
    return os.path.join(_repo_cache_dir(owner, repo), filename)


def _load_cached_list(owner: str, repo: str, filename: str) -> List[Dict[str, Any]]:
    path = _cache_file_path(owner, repo, filename)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"[warn] unable to read cached {filename} for {owner}/{repo}: {exc}")
    return []


def _load_cached_dict(owner: str, repo: str, filename: str) -> Dict[str, Any]:
    path = _cache_file_path(owner, repo, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        print(f"[warn] unable to read cached {filename} for {owner}/{repo}: {exc}")
    return {}


def _parse_github_timestamp(raw: Optional[str]) -> Optional[dt.datetime]:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _github_timestamp_from_dt(value: dt.datetime) -> str:
    value = value.astimezone(dt.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _max_timestamp_from_docs(docs: List[Dict[str, Any]], fields: List[str]) -> Optional[dt.datetime]:
    latest: Optional[dt.datetime] = None
    for doc in docs:
        for field in fields:
            ts = _parse_github_timestamp(doc.get(field))
            if ts and (latest is None or ts > latest):
                latest = ts
    return latest


def _max_commit_timestamp(commits: List[Dict[str, Any]]) -> Optional[dt.datetime]:
    latest: Optional[dt.datetime] = None
    for commit in commits:
        meta = commit.get("commit") or {}
        for key in ("author", "committer"):
            candidate = _parse_github_timestamp(((meta.get(key) or {}).get("date")))
            if candidate and (latest is None or candidate > latest):
                latest = candidate
    return latest


def _cached_blame_head_sha(doc: Dict[str, Any]) -> Optional[str]:
    if not doc:
        return None
    head = doc.get("head_commit_sha")
    if head:
        return head
    files = doc.get("files") or []
    for entry in files:
        sha = entry.get("root_commit_oid")
        if sha:
            return sha
    return None


def _get_changed_files_between_refs(owner: str, repo: str,
                                    base_sha: Optional[str],
                                    head_sha: Optional[str]) -> Optional[List[Dict[str, Optional[str]]]]:
    if not base_sha or not head_sha or base_sha == head_sha:
        return []
    url = f"{BASE_URL}/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    resp = _request("GET", url)
    if resp.status_code != 200:
        _log_http_error(resp, url)
        return None
    payload = resp.json() or {}
    files = payload.get("files") or []
    changed: List[Dict[str, Optional[str]]] = []
    for entry in files:
        changed.append({
            "path": entry.get("filename"),
            "status": entry.get("status"),
            "previous": entry.get("previous_filename"),
        })
    return changed


# --- data retrieval urls ---
def get_repo_meta(owner: str, repo: str) -> Dict[str, Any]:
    """Fetch repository metadata and normalize repo_name field."""
    url = f"{BASE_URL}/repos/{owner}/{repo}"
    resp = _request("GET", url)
    if resp.status_code == 200:
        data = resp.json()
        if "full_name" in data:
            data["repo_name"] = data.pop("full_name")
        else:
            data["repo_name"] = f"{owner}/{repo}"
    else:
        data = {"repo_name": f"{owner}/{repo}"}
    return data


def get_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    """Return all issues (excluding pull requests) for a repository."""
    base_url = f"{BASE_URL}/repos/{owner}/{repo}/issues?state=all"
    cached = _load_cached_list(owner, repo, "issues.json")
    cached_map = {
        issue.get("number"): issue
        for issue in cached
        if isinstance(issue, dict) and issue.get("number") is not None
    }

    latest_ts = _max_timestamp_from_docs(cached, ["updated_at", "closed_at", "created_at"])
    incremental = bool(cached_map and latest_ts)
    url = base_url
    if incremental:
        since = latest_ts - dt.timedelta(seconds=INCREMENTAL_LOOKBACK_SEC)
        url = f"{base_url}&since={quote_plus(_github_timestamp_from_dt(since))}"

    data = _paged_get(url, owner, repo)
    issues = [i for i in data if "pull_request" not in i]
    if not incremental:
        return issues
    if not issues:
        return cached

    order = [issue.get("number") for issue in cached if issue.get("number") is not None]
    for issue in issues:
        num = issue.get("number")
        if num is None:
            continue
        cached_map[num] = issue
        if num in order:
            order.remove(num)
        order.insert(0, num)

    merged = [cached_map[num] for num in order if num in cached_map]
    missing = [num for num in cached_map.keys() if num not in order]
    merged.extend(cached_map[num] for num in missing)
    return merged


def get_pull_requests(owner: str, repo: str) -> List[Dict[str, Any]]:
    """Return all pull requests for a repository."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls?state=all"
    return _paged_get(url, owner, repo)


def get_commits(owner: str, repo: str) -> List[Dict[str, Any]]:
    """Return commit metadata, optionally capped by MAX_PAGES_COMMITS."""
    base_url = f"{BASE_URL}/repos/{owner}/{repo}/commits"
    cached = _load_cached_list(owner, repo, "commits.json")
    cached_map = {
        commit.get("sha"): commit
        for commit in cached
        if isinstance(commit, dict) and commit.get("sha")
    }

    latest_ts = _max_commit_timestamp(cached)
    incremental = bool(cached_map and latest_ts)
    url = base_url
    if incremental:
        since = latest_ts - dt.timedelta(seconds=INCREMENTAL_LOOKBACK_SEC)
        url = f"{base_url}?since={quote_plus(_github_timestamp_from_dt(since))}"

    commits = _paged_get(url, owner, repo, max_pages=MAX_PAGES_COMMITS)
    if not incremental:
        return commits
    if not commits:
        return cached

    order = [commit.get("sha") for commit in cached if commit.get("sha")]
    for commit in commits:
        sha = commit.get("sha")
        if not sha:
            continue
        cached_map[sha] = commit
        if sha in order:
            order.remove(sha)
        order.insert(0, sha)

    merged = [cached_map[sha] for sha in order if sha in cached_map]
    missing = [sha for sha in cached_map.keys() if sha not in order]
    merged.extend(cached_map[sha] for sha in missing)
    return merged


def get_issue_comments(owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
    """Return all comments for a specific issue."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return _paged_get(url, owner, repo)


def get_contributors(owner: str, repo: str) -> List[Dict[str, Any]]:
    """Return GitHub's contributor stats for a repository (one entry per author)."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/contributors"
    return _paged_get(url, owner, repo)


def get_commit_detail(owner, repo, sha):
    """Fetch a commit with diff metadata, caching responses by repo/sha."""
    key = f"{owner}/{repo}@{sha}"
    if key in COMMIT_CACHE:
        return COMMIT_CACHE[key]
    resp = _request("GET", f"{BASE_URL}/repos/{owner}/{repo}/commits/{sha}")
    if resp.status_code == 200:
        data = resp.json()
    elif resp.status_code == 422:
        data = {"error": "invalid_sha"}
    else:
        data = {}
    COMMIT_CACHE[key] = data
    return data


def enrich_commits_with_files(owner: str, repo: str, commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Populate each commit with files_changed / files_changed_count / stats."""
    for commit in commits:
        sha = commit.get("sha")
        detail = get_commit_detail(owner, repo, sha) if sha else {}
        files = (detail or {}).get("files") or []
        filenames = [f.get("filename") for f in files if f.get("filename")]
        commit["files_changed"] = filenames
        commit["files_changed_count"] = len(filenames)
        if detail and detail.get("stats") and "stats" not in commit:
            commit["stats"] = detail["stats"]
    return commits


def get_pr_commits(owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
    """Retrieve commits associated with a pull request."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{number}/commits"
    return _paged_get(url, owner, repo)


def get_commit_message(commit_obj: dict) -> str:
    """Safely extract the commit message text."""
    return ((commit_obj.get("commit") or {}).get("message")) or ""


# --- get prs linked to issues ---
ISSUE_REF_RE = re.compile(
    r"(?:(?P<kw>close[sd]?|fixe?[sd]?|resolve[sd]?)\s*[:\-–—]*\s+)?"
    r"(?:(?P<full>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<num1>\d+)|#(?P<num2>\d+))",
    flags=re.IGNORECASE
)


def extract_issue_refs_detailed(text: str) -> List[Dict[str, Any]]:
    """Parse sentences for issue references, returning metadata about matches."""
    out: List[Dict[str, Any]] = []
    if not text:
        return out

    sentences = re.split(r'(?<=[\.\!\?\n])\s+', text)

    for sent in sentences:
        if not sent:
            continue
        sentence_has_kw = bool(re.search(r'\b(close[sd]?|fixe?[sd]?|resolve[sd]?)\b', sent, re.IGNORECASE))
        for m in ISSUE_REF_RE.finditer(sent):
            full_repo = m.group("full")
            num = m.group("num1") or m.group("num2")
            if not num:
                continue
            has_kw_here = bool(m.group("kw")) or sentence_has_kw
            out.append({
                "full_repo": full_repo,
                "number": int(num),
                "has_closing_kw": has_kw_here,
            })
    return out


def find_prs_with_linked_issues(owner: str, repo: str,
                                prs: List[Dict[str, Any]],
                                local_issues: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Discover PRs referencing issues via titles, bodies, commits, or merge messages."""
    results: List[Dict[str, Any]] = []
    issue_author_cache: Dict[Tuple[str, int], Optional[str]] = {}
    pr_commits_cache: Dict[int, List[Dict[str, Any]]] = {}

    if local_issues:
        for i in local_issues:
            issue_author_cache[(f"{owner}/{repo}".lower(), i["number"])] = ((i.get("user") or {}).get("login"))

    all_refs: Dict[int, Dict[str, Any]] = {}
    for pr in prs:
        pr_number = pr.get("number")
        title, body = pr.get("title") or "", pr.get("body") or ""
        merged = bool(pr.get("merged_at")) if "merged_at" in pr else bool(pr.get("merged", False))
        pr_author = (pr.get("user") or {}).get("login")
        links: List[Dict[str, Any]] = []

        def _add_ref(ref, ref_source_type: str):
            ref_repo = ref["full_repo"] or f"{owner}/{repo}"
            issue_num = ref["number"]
            links.append({
                "referenced_repo": ref_repo,
                "issue_number": issue_num,
                "reference_type": ref_source_type,
                "has_closing_kw": ref["has_closing_kw"],
                "would_auto_close": merged and ref["has_closing_kw"],
            })

        # a) pr title/body refs
        for ref in extract_issue_refs_detailed(f"{title}\n{body}"):
            _add_ref(ref, "pr_text")

        # b) pr commit messages (reuse cache)
        pr_commits = pr_commits_cache.get(pr_number)
        if pr_commits is None:
            pr_commits = get_pr_commits(owner, repo, pr_number) or []
            pr_commits_cache[pr_number] = pr_commits

        for c in pr_commits:
            msg = get_commit_message(c)
            if not msg:
                continue
            for ref in extract_issue_refs_detailed(msg):
                _add_ref(ref, "commit_message")

        # c) merge commit message (only fetch if different than pr body)
        merge_sha = pr.get("merge_commit_sha")
        if merge_sha and (not body or len(body) < 10 or "squash" not in body.lower()):
            commit_detail = get_commit_detail(owner, repo, merge_sha)
            if commit_detail.get("error") == "invalid_sha":
                continue
            msg = ((commit_detail.get("commit") or {}).get("message")) or ""
            for ref in extract_issue_refs_detailed(msg):
                _add_ref(ref, "merge_commit_message")

        if links:
            all_refs[pr_number] = {
                "links": links,
                "merged": merged,
                "author": pr_author,
                "title": title,
                "url": pr.get("html_url"),
                "state": pr.get("state"),
                "created_at": pr.get("created_at") or pr.get("updated_at"),
            }

    unique_refs = {(r["referenced_repo"].lower(), r["issue_number"])
                   for refs in all_refs.values()
                   for r in refs["links"]}

    for (ref_repo, issue_num) in unique_refs:
        if (ref_repo, issue_num) not in issue_author_cache:
            try:
                ref_owner, ref_name = ref_repo.split("/")
                issue_data = get_issue_or_pr_details(ref_owner, ref_name, issue_num)
                issue_author = ((issue_data or {}).get("user") or {}).get("login")
                issue_author_cache[(ref_repo, issue_num)] = issue_author
            except Exception as e:
                print(f"[warn] failed to fetch issue {ref_repo}#{issue_num}: {e}")
                issue_author_cache[(ref_repo, issue_num)] = None

    for pr_number, info in all_refs.items():
        for ref in info["links"]:
            key = (ref["referenced_repo"].lower(), ref["issue_number"])
            ref["issue_author"] = issue_author_cache.get(key)
        results.append({
            "repo_name": f"{owner}/{repo}",
            "pr_number": pr_number,
            "title": info["title"],
            "author": info["author"],
            "state": info["state"],
            "merged": info["merged"],
            "links": info["links"],
            "url": info["url"],
            "created_at": info["created_at"],
        })

    return results


def find_issues_closed_by_repo_commits(owner: str, repo: str, commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return commit→issue linkage rows when commit messages contain closing keywords."""
    results: List[Dict[str, Any]] = []
    issue_author_cache: Dict[Tuple[str, int], Optional[str]] = {}

    for c in commits:
        msg = ((c.get("commit") or {}).get("message")) or ""
        if not msg:
            continue

        commit_author = None
        if c.get("author") and isinstance(c["author"], dict):
            commit_author = c["author"].get("login")
        if not commit_author:
            commit_author = ((c.get("commit") or {}).get("author") or {}).get("name")

        for ref in extract_issue_refs_detailed(msg):
            if not ref["has_closing_kw"]:
                continue

            ref_repo = ref["full_repo"] or f"{owner}/{repo}"
            ref_owner, ref_name = ref_repo.split("/")
            issue_num = ref["number"]
            issue_key = (ref_repo.lower(), issue_num)

            if issue_key in issue_author_cache:
                issue_author = issue_author_cache[issue_key]
            else:
                issue_data = get_issue_or_pr_details(ref_owner, ref_name, issue_num)
                issue_author = ((issue_data or {}).get("user") or {}).get("login")
                issue_author_cache[issue_key] = issue_author

            results.append({
                "repo_name": f"{owner}/{repo}",
                "commit_sha": c.get("sha"),
                "commit_url": c.get("html_url"),
                "commit_author": commit_author,
                "referenced_repo": ref_repo,
                "issue_number": issue_num,
                "issue_author": issue_author,
                "reference_type": "commit_message",
                "has_closing_kw": True,
                "would_auto_close": True,
            })

    return results


# --- cross-repo references (issues + prs, with timestamps) ---
CROSS_REPO_RE = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)", re.IGNORECASE)


def _parse_full_repo(full_repo: str) -> Tuple[str, str]:
    """Split \"owner/repo\" strings and trim whitespace leftovers."""
    owner, repo = full_repo.split("/", 1)
    return owner.strip(), repo.strip()


def get_issue_or_pr_details(owner: str, repo: str, number: int) -> dict:
    """Fetch issue/PR details with caching to minimize duplicate API calls."""
    key = f"{owner}/{repo}#{number}".lower()
    if key in ISSUE_DETAIL_CACHE:
        return ISSUE_DETAIL_CACHE[key]
    resp = _request("GET", f"{BASE_URL}/repos/{owner}/{repo}/issues/{number}")
    data = resp.json() if resp.status_code == 200 else {}
    ISSUE_DETAIL_CACHE[key] = data
    return data


def classify_issue_or_pr(details: dict) -> str:
    """Return the document type (issue vs PR) based on GitHub response shape."""
    return "pull_request" if details and details.get("pull_request") else "issue"


def _source_text_buckets_for_issue_like(owner: str, repo: str, issue_like: dict):
    """Yield reference buckets (title/body) with timestamps for the provided artifact."""
    number = issue_like.get("number")
    created_at = issue_like.get("created_at") or issue_like.get("updated_at")
    title = issue_like.get("title") or ""
    body = issue_like.get("body") or ""
    yield ("issue_title", title, created_at)
    yield ("issue_body", body, created_at)


def find_cross_project_links_issues_and_prs(owner: str, repo: str, issues: List[Dict[str, Any]], prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify cross-repo mentions by scanning text and caching referenced targets."""
    results: List[Dict[str, Any]] = []
    this_repo_full = f"{owner}/{repo}".lower()
    target_cache: Dict[Tuple[str, int], Optional[dict]] = {}

    def _source_iter():
        """Yield both issues and pull requests uniformly."""
        for issue in issues:
            yield ("issue", issue)
        for pr in prs:
            yield ("pull_request", {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "body": pr.get("body"),
                "created_at": pr.get("created_at") or pr.get("updated_at"),
                "html_url": pr.get("html_url"),
            })

    for source_type, source in _source_iter():
        source_number = source.get("number")
        source_url = source.get("html_url")
        source_created_at = source.get("created_at") or source.get("updated_at")

        for where, text, seen_at in _source_text_buckets_for_issue_like(owner, repo, source):
            if not text:
                continue

            for m in CROSS_REPO_RE.finditer(text):
                target_full = m.group(1)
                target_num = int(m.group(2))
                if target_full.lower() == this_repo_full:
                    continue

                tgt_owner, tgt_repo = _parse_full_repo(target_full)
                cache_key = (target_full.lower(), target_num)

                if cache_key in target_cache:
                    target_details = target_cache[cache_key]
                else:
                    target_details = get_issue_or_pr_details(tgt_owner, tgt_repo, target_num)
                    target_cache[cache_key] = target_details

                target_type = classify_issue_or_pr(target_details)
                target_created_at = target_details.get("created_at") or target_details.get("updated_at")
                target_url = target_details.get("html_url")
                target_author = ((target_details.get("user") or {}).get("login")) if target_details else None

                results.append({
                    "source": {
                        "repo_name": f"{owner}/{repo}",
                        "type": source_type,
                        "number": source_number,
                        "url": source_url,
                        "created_at": source_created_at,
                    },
                    "reference": {
                        "found_in": where,
                        "seen_at": seen_at,
                        "cross_ref_timestamp": seen_at,
                    },
                    "target": {
                        "repo_name": target_full,
                        "type": target_type,
                        "number": target_num,
                        "url": target_url,
                        "created_at": target_created_at,
                        "author": target_author,
                    },
                })

        if len(results) % 50 == 0 and len(results) > 0:
            print(f"  found {len(results)} cross-repo references so far...")

    return results


# --- main orchestration ---
def process_repo(full_name: str) -> None:
    """Run the end-to-end pipeline for `owner/repo` and persist JSON outputs."""
    owner, repo = full_name.split("/", 1)
    out_dir = os.path.join(OUTPUT_DIR, f"{owner}_{repo}")
    ensure_dir(out_dir)

    print(f"\n=== {owner}/{repo} ===")

    print("  fetching repo metadata...")
    repo_meta = get_repo_meta(owner, repo)
    save_json(f"{out_dir}/repo_meta.json", repo_meta)

    print("  fetching issues...")
    issues = get_issues(owner, repo)
    save_json(f"{out_dir}/issues.json", issues)

    print("  fetching pull requests...")
    prs = get_pull_requests(owner, repo)
    save_json(f"{out_dir}/pull_requests.json", prs)

    print("  fetching contributors...")
    contributors = get_contributors(owner, repo)
    save_json(f"{out_dir}/contributors.json", contributors)

    print("  fetching commits...")
    commits = get_commits(owner, repo)
    commits = enrich_commits_with_files(owner, repo, commits)
    save_json(f"{out_dir}/commits.json", commits)

    print("  fetching git blame snapshots...")
    repo_blame = collect_repo_blame(owner, repo, repo_meta, commits)
    save_json(f"{out_dir}/repo_blame.json", repo_blame)

    print("  fetching prs with issue references...")
    pr_links = find_prs_with_linked_issues(owner, repo, prs)
    save_json(f"{out_dir}/prs_with_linked_issues.json", pr_links)

    print("  fetching issues closed by repo commits...")
    closed_by_commits = find_issues_closed_by_repo_commits(owner, repo, commits)
    save_json(f"{out_dir}/issues_closed_by_commits.json", closed_by_commits)

    print("  fetching cross-repo references (issues & PRs)...")
    cross_links = find_cross_project_links_issues_and_prs(owner, repo, issues, prs)
    save_json(f"{out_dir}/cross_repo_links.json", cross_links)

    print(f"    DONE EXTRACTING DATA → {out_dir}")


def main(custom_repos: Optional[List[str]] = None) -> None:
    """Entry point used by both CLI and imports; accepts optional repo overrides."""
    repos = custom_repos or REPOS
    if not repos:
        print("No repositories specified. Provide CLI args or edit REPOS in the file.")
        sys.exit(1)

    ensure_dir(OUTPUT_DIR)
    print(f"Processing {len(repos)} repos...")
    for r in repos:
        try:
            process_repo(r.strip())
        except Exception as e:
            print(f"[error] {r}: {e}")
    print("\nAll repositories processed.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main([arg for arg in sys.argv[1:] if "/" in arg])
    else:
        main()
