"""
initial_pipeline.py
-------------------
A unified GitHub data pipeline that automates the retrieval and linking of repository data
using the GitHub REST API (v3). This script consolidates multiple data-collection processes
into a single end-to-end workflow for reproducible, large-scale analysis.

Functionality:
    • Collects repository-level metadata, issues, pull requests, and commits.
    • Extracts and analyzes commit-level information (SHAs, parents, diffs, file changes).
    • Detects issue references in PRs and commits (e.g., "closes #123", "fixes org/repo#45").
    • Identifies cross-repository relationships by scanning issue and PR bodies/comments.
    • Builds commit lineage structures, linking each commit to its parent SHAs and prior edits.
    • Aggregates summary metrics describing repository activity and linkage statistics.

Outputs (per repository):
    output/{owner_repo}/
        repo_meta.json              – Repository metadata (stars, forks, watchers, open issues)
        issues.json                 – All issues (open and closed)
        pull_requests.json          – All pull requests (merged, open, closed)
        commits.json                – Commit metadata (SHA, author, message, date)
        prs_with_linked_issues.json – PRs referencing or closing issues
        issues_closed_by_commits.json – Issues closed directly via commit messages
        cross_repo_links.json       – Cross-repository links (issues and PRs)
        summary_metrics.json        – Aggregated metrics summarizing repository activity

Usage:
    python3 initial_pipeline.py
    python3 initial_pipeline.py owner/repo [owner2/repo2 ...]

Notes:
    - Requires a GitHub Personal Access Token with read access to public repositories.
    - Implements rate-limit detection, exponential backoff, and retry logic for reliability.
    - Designed for extensibility (future integration with GraphQL v4 or Elasticsearch indexing).

TO DO
    - [x] Research and see if we can add git blame functionality to see who touches the file to initial_pipeline.py.
    - [x] Refine initial_pipeline.py to include repo_name in each entry of each json file so there is a universal indicator for each entry to search
    - [x] Add functionality to cycle through GH API tokens when rate limits are hit.
    - [x] Create tests for initial_pipeline.py (aim for greater than 90% test coverage).
    - [x] Verify data pulled from initial_pipeline.py.
    - [ ] Update the python file used to index the data into elasticsearch following the new schema from initial_pipeline.py.
"""

import os, re, json, sys, time, requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import quote

# --- Configuration ---
GITHUB_TOKENS = []
GITHUB_TOKEN_INDEX = 0
TOKEN_COUNTER = 0
USER_AGENT = "cosc448-initial-pipeline/1.0 (+abijeet)"
BASE_URL = "https://api.github.com"
REPOS = [
    # "carsondrobe/fellas"
    # "rollup/rollup"
    "prettier/prettier", 
    # "micromatch/micromatch", 
    # "standard", 
    # "nyc", 
    # "laravel-mix", 
    # "redux", 
    # "axios"
]
PER_PAGE = 100
REQUEST_TIMEOUT = 30
MAX_RETRIES = len(GITHUB_TOKENS) * 2
BACKOFF_BASE_SEC = 2
OUTPUT_DIR = "./output"

# --- HTTP Setup ---
SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"token {GITHUB_TOKENS[0]}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": USER_AGENT,
})

# --- Sleep ---
def _sleep_with_jitter(base: float) -> None:
    jitter = base * 0.25 * (0.5 - (os.urandom(1)[0] / 255.0))
    time.sleep(max(0.0, base + jitter))

# --- HTTP Request ---
def _request(method: str, url: str) -> requests.Response:
    """ HTTP request with retry and rate limit handling. """
    for attempt in range(1, MAX_RETRIES + 1):
        try:   
            resp = SESSION.request(method, url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 403:
                reset = resp.headers.get("X-RateLimit-Reset")
                if reset and reset.isdigit():
                    if TOKEN_COUNTER < len(GITHUB_TOKENS):
                        GITHUB_TOKEN_INDEX += 1
                        tokens_left = len(GITHUB_TOKENS) - GITHUB_TOKEN_INDEX
                        print(f"Switching to GITHUB TOKEN {GITHUB_TOKEN_INDEX}.\nThere are {tokens_left} tokens left.")
                        SESSION.headers.update({
                            "Authorization": f"token {GITHUB_TOKENS[GITHUB_TOKEN_INDEX]}",
                            "Accept": "application/vnd.github.v3+json",
                            "User-Agent": USER_AGENT,
                        })
                    else:
                        reset_ts = int(reset)
                        wait_sec = max(0, reset_ts - int(time.time())) + 5
                        print(f"[rate-limit] waiting {wait_sec}s until reset...")
                        time.sleep(wait_sec)
                        continue
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(int(retry_after) + 1)
                    continue
                msg = (resp.json().get("message") or "").lower() if resp.headers.get("content-type","").startswith("application/json") else ""
                if "abuse detection" in msg:
                    backoff = BACKOFF_BASE_SEC * 2
                    print(f"[abuse-detect] backing off {backoff:.1f}s...")
                    _sleep_with_jitter(backoff)
                    continue
            if resp.status_code in (500, 502, 503, 504):
                raise requests.RequestException(f"Server error {resp.status_code}")
            return resp
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            backoff = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"[retry {attempt}/{MAX_RETRIES}] {e} -> sleep {backoff:.1f}s")
            _sleep_with_jitter(backoff)
    raise RuntimeError("Exceeded max retries")

# --- Get Info For URL ---
def _paged_get(url: str, owner: str, repo: str) -> List[Dict[str, Any]]:
    """ Automatically retrieve all pages until API returns empty results. """
    results: List[Dict[str, Any]] = []
    page = 1
    while True:
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}per_page={PER_PAGE}&page={page}"
        resp = _request("GET", page_url)
        if resp.status_code != 200:
            print(f"[warn] {page_url} → {resp.status_code}")
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

# --- Data Retrieval URLs---
def get_repo_meta(owner: str, repo: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/repos/{owner}/{repo}"
    resp = _request("GET", url)
    if resp.status_code == 200:
        data = resp.json()
        data["repo_name"] = data.pop("full_name")
    else:
        data = {}
    return data

def get_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues?state=all"
    data = _paged_get(url, owner, repo)
    return [i for i in data if "pull_request" not in i]

def get_pull_requests(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls?state=all"
    return _paged_get(url, owner, repo)

def get_commits(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/commits"
    return _paged_get(url, owner, repo)

def get_issue_comments(owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return _paged_get(url, owner, repo)

def get_commit_detail(owner: str, repo: str, sha: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/commits/{sha}"
    resp = _request("GET", url)
    return resp.json() if resp.status_code == 200 else {}

def get_pr_commits(owner: str, repo: str, number: int):
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{number}/commits"
    return _paged_get(url, owner, repo) 

def get_commit_message(commit_obj: dict) -> str:
    return ((commit_obj.get("commit") or {}).get("message")) or ""


# --- SECTION: Get PRs Linked To Issues ---
ISSUE_REF_RE = re.compile(
    r"(?:(?P<kw>close[sd]?|fixe?[sd]?|resolve[sd]?)\s*[:\-–—]*\s+)?"
    r"(?:(?P<full>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<num1>\d+)|#(?P<num2>\d+))",
    flags=re.IGNORECASE
)

def extract_issue_refs_detailed(text: str):
    out = []
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
    results: List[Dict[str, Any]] = []
    issue_author_cache: Dict[Tuple[str, int], Optional[str]] = {}
    pr_commits_cache: Dict[int, List[Dict[str, Any]]] = {}

    if local_issues:
        for i in local_issues:
            issue_author_cache[(f"{owner}/{repo}".lower(), i["number"])] = ((i.get("user") or {}).get("login"))

    all_refs: Dict[int, List[Dict[str, Any]]] = {}  
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

        # A) PR title/body refs
        for ref in extract_issue_refs_detailed(f"{title}\n{body}"):
            _add_ref(ref, "pr_text")

        # B) PR commit messages (reuse cache)
        if pr_number in pr_commits_cache:
            pr_commits = pr_commits_cache[pr_number]
        else:
            pr_commits = get_pr_commits(owner, repo, pr_number) or []
            pr_commits_cache[pr_number] = pr_commits

        for c in pr_commits:
            msg = get_commit_message(c)
            if not msg:
                continue
            for ref in extract_issue_refs_detailed(msg):
                _add_ref(ref, "commit_message")

        # C) Merge commit message (only fetch if different than PR body)
        merge_sha = pr.get("merge_commit_sha")
        if merge_sha and (not body or len(body) < 10 or "squash" not in body.lower()):
            commit_detail = get_commit_detail(owner, repo, merge_sha)
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
    results = []
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


# --- SECTION: Cross-Repo References (issues + PRs, with timestamps) ---
CROSS_REPO_RE = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)", re.IGNORECASE)

def _parse_full_repo(full_repo: str) -> Tuple[str, str]:
    owner, repo = full_repo.split("/", 1)
    return owner.strip(), repo.strip()

def get_issue_or_pr_details(owner: str, repo: str, number: int) -> dict:
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{number}"
    resp = _request("GET", url)
    return resp.json() if resp.status_code == 200 else {}

def classify_issue_or_pr(details: dict) -> str:
    return "pull_request" if details and details.get("pull_request") else "issue"

def _source_text_buckets_for_issue_like(owner: str, repo: str, issue_like: dict):
    number = issue_like.get("number")
    created_at = issue_like.get("created_at") or issue_like.get("updated_at")
    title = issue_like.get("title") or ""
    body = issue_like.get("body") or ""
    yield ("issue_title", title, created_at)
    yield ("issue_body", body, created_at)

    comments = get_issue_comments(owner, repo, number)
    for c in comments:
        yield ("issue_comment", c.get("body") or "", c.get("created_at") or c.get("updated_at") or created_at)

def find_cross_project_links_issues_and_prs(owner: str, repo: str, issues: List[Dict[str, Any]], prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

# --- Helpers ---
def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- Main Orchestration ---
def process_repo(full_name: str) -> None:
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

    print("  fetching commits...")
    commits = get_commits(owner, repo)
    save_json(f"{out_dir}/commits.json", commits)

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
