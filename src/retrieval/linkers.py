"""Functions that identify relationships among issues, PRs, commits, and repos."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .config import BASE_URL
from .collectors import (
    ISSUE_DETAIL_CACHE,
    get_commit_detail,
    get_commit_message,
    get_pr_commits,
)
from .http_client import request_with_backoff

ISSUE_REF_RE = re.compile(
    r"(?:(?P<kw>close[sd]?|fixe?[sd]?|resolve[sd]?)\s*[:\-–—]*\s+)?"
    r"(?:(?P<full>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<num1>\d+)|#(?P<num2>\d+))",
    flags=re.IGNORECASE,
)
CROSS_REPO_RE = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)", re.IGNORECASE)


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
        for match in ISSUE_REF_RE.finditer(sent):
            full_repo = match.group("full")
            number = match.group("num1") or match.group("num2")
            if not number:
                continue
            has_kw_here = bool(match.group("kw")) or sentence_has_kw
            out.append({
                "full_repo": full_repo,
                "number": int(number),
                "has_closing_kw": has_kw_here,
            })
    return out


def find_prs_with_linked_issues(owner: str, repo: str,
                                prs: List[Dict[str, Any]],
                                local_issues: Optional[List[Dict[str, Any]]] = None,
                                max_prs: int = 0) -> List[Dict[str, Any]]:
    """Discover PRs referencing issues via titles, bodies, commits, or merge messages."""
    results: List[Dict[str, Any]] = []
    issue_author_cache: Dict[Tuple[str, int], Optional[str]] = {}
    pr_commits_cache: Dict[int, List[Dict[str, Any]]] = {}
    pr_candidates = prs or []
    total_prs = len(pr_candidates)

    if max_prs and len(pr_candidates) > max_prs:
        pr_candidates = sorted(
            pr_candidates,
            key=lambda pr: (pr.get("created_at") or pr.get("updated_at") or ""),
            reverse=True,
        )[:max_prs]
        print(f"  limiting PR linkage scan to {len(pr_candidates)} of {total_prs} PRs (MAX_PRS_WITH_LINKED_ISSUES={max_prs})")

    if local_issues:
        for issue in local_issues:
            issue_author_cache[(f"{owner}/{repo}".lower(), issue["number"])] = ((issue.get("user") or {}).get("login"))

    all_refs: Dict[int, Dict[str, Any]] = {}
    for pr in pr_candidates:
        pr_number = pr.get("number")
        title, body = pr.get("title") or "", pr.get("body") or ""
        merged = bool(pr.get("merged_at")) if "merged_at" in pr else bool(pr.get("merged", False))
        pr_author = (pr.get("user") or {}).get("login")
        links: List[Dict[str, Any]] = []

        def _add_ref(ref: Dict[str, Any], ref_source_type: str) -> None:
            ref_repo = ref["full_repo"] or f"{owner}/{repo}"
            issue_num = ref["number"]
            links.append({
                "referenced_repo": ref_repo,
                "issue_number": issue_num,
                "reference_type": ref_source_type,
                "has_closing_kw": ref["has_closing_kw"],
                "would_auto_close": merged and ref["has_closing_kw"],
            })

        for ref in extract_issue_refs_detailed(f"{title}\n{body}"):
            _add_ref(ref, "pr_text")

        pr_commits = pr_commits_cache.get(pr_number)
        if pr_commits is None:
            pr_commits = get_pr_commits(owner, repo, pr_number) or []
            pr_commits_cache[pr_number] = pr_commits

        for commit in pr_commits:
            message = get_commit_message(commit)
            if not message:
                continue
            for ref in extract_issue_refs_detailed(message):
                _add_ref(ref, "commit_message")

        merge_sha = pr.get("merge_commit_sha")
        if merge_sha and (not body or len(body) < 10 or "squash" not in body.lower()):
            commit_detail = get_commit_detail(owner, repo, merge_sha)
            if commit_detail.get("error") == "invalid_sha":
                continue
            message = ((commit_detail.get("commit") or {}).get("message")) or ""
            for ref in extract_issue_refs_detailed(message):
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

    unique_refs = {(ref["referenced_repo"].lower(), ref["issue_number"])
                   for refs in all_refs.values()
                   for ref in refs["links"]}

    for ref_repo, issue_num in unique_refs:
        if (ref_repo, issue_num) not in issue_author_cache:
            try:
                ref_owner, ref_name = ref_repo.split("/")
                issue_data = get_issue_or_pr_details(ref_owner, ref_name, issue_num)
                issue_author = ((issue_data or {}).get("user") or {}).get("login")
                issue_author_cache[(ref_repo, issue_num)] = issue_author
            except Exception as exc:
                print(f"[warn] failed to fetch issue {ref_repo}#{issue_num}: {exc}")
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

    for commit in commits:
        message = ((commit.get("commit") or {}).get("message")) or ""
        if not message:
            continue

        commit_author = None
        if commit.get("author") and isinstance(commit["author"], dict):
            commit_author = commit["author"].get("login")
        if not commit_author:
            commit_author = ((commit.get("commit") or {}).get("author") or {}).get("name")

        for ref in extract_issue_refs_detailed(message):
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
                "commit_sha": commit.get("sha"),
                "commit_url": commit.get("html_url"),
                "commit_author": commit_author,
                "referenced_repo": ref_repo,
                "issue_number": issue_num,
                "issue_author": issue_author,
                "reference_type": "commit_message",
                "has_closing_kw": True,
                "would_auto_close": True,
            })

    return results


def _parse_full_repo(full_repo: str) -> Tuple[str, str]:
    """Split "owner/repo" strings and trim whitespace leftovers."""
    owner, repo_name = full_repo.split("/", 1)
    return owner.strip(), repo_name.strip()


def get_issue_or_pr_details(owner: str, repo: str, number: int) -> dict:
    """Fetch issue/PR details with caching to minimize duplicate API calls."""
    key = f"{owner}/{repo}#{number}".lower()
    if key in ISSUE_DETAIL_CACHE:
        return ISSUE_DETAIL_CACHE[key]
    resp = request_with_backoff("GET", f"{BASE_URL}/repos/{owner}/{repo}/issues/{number}")
    data = resp.json() if resp.status_code == 200 else {}
    ISSUE_DETAIL_CACHE[key] = data
    return data


def classify_issue_or_pr(details: dict) -> str:
    """Return the document type (issue vs PR) based on GitHub response shape."""
    return "pull_request" if details and details.get("pull_request") else "issue"


def _source_text_buckets_for_issue_like(owner: str, repo: str, issue_like: dict):
    """Yield reference buckets (title/body) with timestamps for the provided artifact."""
    created_at = issue_like.get("created_at") or issue_like.get("updated_at")
    title = issue_like.get("title") or ""
    body = issue_like.get("body") or ""
    yield ("issue_title", title, created_at)
    yield ("issue_body", body, created_at)


def find_cross_project_links_issues_and_prs(owner: str, repo: str,
                                            issues: List[Dict[str, Any]],
                                            prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify cross-repo mentions by scanning text and caching referenced targets."""
    results: List[Dict[str, Any]] = []
    this_repo_full = f"{owner}/{repo}".lower()
    target_cache: Dict[Tuple[str, int], Optional[dict]] = {}

    def _source_iter():
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

            for match in CROSS_REPO_RE.finditer(text):
                target_full = match.group(1)
                target_num = int(match.group(2))
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


__all__ = [
    "extract_issue_refs_detailed",
    "find_prs_with_linked_issues",
    "find_issues_closed_by_repo_commits",
    "get_issue_or_pr_details",
    "classify_issue_or_pr",
    "find_cross_project_links_issues_and_prs",
]
