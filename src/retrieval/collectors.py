"""Data collection helpers for repositories, issues, commits, and blame snapshots."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus

from .config import (
    BASE_URL,
    BLAME_EXAMPLE_LIMIT,
    BLAME_FILE_LIMIT,
    GITHUB_TOKENS,
    INCREMENTAL_LOOKBACK_SEC,
    MAX_PAGES_COMMITS,
    OUTPUT_DIR,
)
from .http_client import log_http_error, paged_get, request_with_backoff, run_graphql_query

ISSUE_DETAIL_CACHE: Dict[str, dict] = {}
COMMIT_CACHE: Dict[str, dict] = {}


def ensure_dir(path: str) -> None:
    """Create output directories as-needed without raising for existing folders."""
    os.makedirs(path, exist_ok=True)


def save_json(path: str, data: Any) -> None:
    """Write JSON to disk using UTF-8 and deterministic formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
    resp = request_with_backoff("GET", url)
    if resp.status_code != 200:
        log_http_error(resp, url)
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
        for entry in (cached_doc.get("files") or []) if entry.get("path")
    } if cached_doc else {}
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


def _repo_cache_dir(owner: str, repo: str) -> str:
    path = os.path.join(OUTPUT_DIR, f"{owner}_{repo}")
    ensure_dir(path)
    return path


def _cache_file_path(owner: str, repo: str, filename: str) -> str:
    return os.path.join(_repo_cache_dir(owner, repo), filename)


def _load_cached_list(owner: str, repo: str, filename: str) -> List[Dict[str, Any]]:
    path = _cache_file_path(owner, repo, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def _load_cached_dict(owner: str, repo: str, filename: str) -> Dict[str, Any]:
    path = _cache_file_path(owner, repo, filename)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _parse_github_timestamp(raw: Optional[str]) -> Optional[dt.datetime]:
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _github_timestamp_from_dt(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _max_timestamp_from_docs(docs: List[Dict[str, Any]], fields: List[str]) -> Optional[dt.datetime]:
    best = None
    for doc in docs:
        for field in fields:
            ts = _parse_github_timestamp(doc.get(field))
            if not ts:
                continue
            if not best or ts > best:
                best = ts
    return best


def _max_commit_timestamp(commits: List[Dict[str, Any]]) -> Optional[dt.datetime]:
    fields = [
        "commit.author.date",
        "commit.committer.date",
        "author.date",
        "committer.date",
    ]
    best = None
    for commit in commits:
        for field in fields:
            obj = commit
            for part in field.split('.'):
                obj = obj.get(part) if isinstance(obj, dict) else None
                if obj is None:
                    break
            if not obj:
                continue
            ts = _parse_github_timestamp(obj) if isinstance(obj, str) else None
            if not ts:
                continue
            if not best or ts > best:
                best = ts
    return best


def _ensure_commit_file_metadata(owner: str,
                                 repo: str,
                                 commits: List[Dict[str, Any]],
                                 missing: Optional[Set[str]] = None) -> None:
    missing = missing or {c.get("sha") for c in commits if c.get("sha")}
    for commit in commits:
        sha = commit.get("sha")
        if not sha or missing and sha not in missing:
            continue
        detail = get_commit_detail(owner, repo, sha)
        if not detail:
            continue
        commit["files"] = detail.get("files")
        commit["stats"] = detail.get("stats")


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
    resp = request_with_backoff("GET", url)
    if resp.status_code != 200:
        log_http_error(resp, url)
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


def get_repo_meta(owner: str, repo: str) -> Dict[str, Any]:
    """Fetch repository metadata and normalize repo_name field."""
    url = f"{BASE_URL}/repos/{owner}/{repo}"
    resp = request_with_backoff("GET", url)
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

    data = paged_get(url, owner, repo)
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
    return paged_get(url, owner, repo)


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

    commits = paged_get(url, owner, repo, max_pages=MAX_PAGES_COMMITS)
    fetched_shas = [c.get("sha") for c in commits if c.get("sha")]
    if not incremental:
        _ensure_commit_file_metadata(owner, repo, commits)
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
    _ensure_commit_file_metadata(owner, repo, merged, set(fetched_shas))
    return merged


def get_issue_comments(owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
    """Return all comments for a specific issue."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return paged_get(url, owner, repo)


def get_contributors(owner: str, repo: str) -> List[Dict[str, Any]]:
    """Return GitHub's contributor stats for a repository (one entry per author)."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/contributors"
    return paged_get(url, owner, repo)


def get_commit_detail(owner: str, repo: str, sha: str):
    """Fetch a commit with diff metadata, caching responses by repo/sha."""
    key = f"{owner}/{repo}@{sha}"
    if key in COMMIT_CACHE:
        return COMMIT_CACHE[key]
    resp = request_with_backoff("GET", f"{BASE_URL}/repos/{owner}/{repo}/commits/{sha}")
    if resp.status_code == 200:
        data = resp.json()
    elif resp.status_code == 422:
        data = {"error": "invalid_sha"}
    else:
        data = {}
    COMMIT_CACHE[key] = data
    return data


def get_pr_commits(owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
    """Retrieve commits associated with a pull request."""
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{number}/commits"
    return paged_get(url, owner, repo)


def get_commit_message(commit_obj: dict) -> str:
    """Safely extract the commit message text."""
    return ((commit_obj.get("commit") or {}).get("message")) or ""


__all__ = [
    "ISSUE_DETAIL_CACHE",
    "COMMIT_CACHE",
    "ensure_dir",
    "save_json",
    "author_key_from_commit_author",
    "one_line",
    "fetch_file_blame",
    "collect_repo_blame",
    "get_repo_meta",
    "get_issues",
    "get_pull_requests",
    "get_commits",
    "get_issue_comments",
    "get_contributors",
    "get_commit_detail",
    "get_pr_commits",
    "get_commit_message",
]
