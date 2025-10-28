"""
    initial_pipeline.py
---
    This file combines the following scripts:
        1) v3_data_retrieval.py - GitHub V3 data retrieval (issues, PRs, commits, repo meta)
        2) find_prs_with_linked_issues.py - PRs with linked issues (closes/fixes/resolves + #123 / owner/repo#123)
        3) cross_project_issue_links.py - Cross-project issue links (owner/repo#123 mentioned in issue bodies/comments)
        4) commit_diff_retrieval.py - Commit diffs (files changed, additions, deletions, no patches)

    Output (per repo):
        output/{owner_repo}/
            repo_meta.json
            issues.json
            pull_requests.json
            commits.json
            cross_repo_links.json
            commit_lineage.json
            summary_metrics.json 
    
"""

import os, re, json, sys, time, requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import quote

# --- Configuration ---
GITHUB_TOKEN = ""
USER_AGENT = "cosc448-initial-pipeline/1.0 (+abijeet)"
BASE_URL = "https://api.github.com"
REPOS = [
    # "carsondrobe/fellas"
    # "rollup/rollup"
    # "prettier", 
    "micromatch/micromatch", 
    # "standard", 
    # "nyc", 
    # "laravel-mix", 
    # "redux", 
    # "axios"
]
PER_PAGE = 100
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5
BACKOFF_BASE_SEC = 2
OUTPUT_DIR = "output"

# --- HTTP Setup ---
SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"token {GITHUB_TOKEN}",
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
def _paged_get(url: str) -> List[Dict[str, Any]]:
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
        results.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return results

# --- Data Retrieval URLs---
def get_repo_meta(owner: str, repo: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/repos/{owner}/{repo}"
    resp = _request("GET", url)
    return resp.json() if resp.status_code == 200 else {}

def get_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues?state=all"
    data = _paged_get(url)
    return [i for i in data if "pull_request" not in i]

def get_pull_requests(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls?state=all"
    return _paged_get(url)

def get_commits(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/commits"
    return _paged_get(url)

def get_issue_comments(owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return _paged_get(url)

def get_commit_detail(owner: str, repo: str, sha: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/commits/{sha}"
    resp = _request("GET", url)
    return resp.json() if resp.status_code == 200 else {}

def get_pr_commits(owner: str, repo: str, number: int):
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{number}/commits"
    return _paged_get(url) 

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
    """
    Find PRs that reference issues (closes/fixes/resolves + #123 or owner/repo#123),
    with author lookups optimized using caching and batching.
    """
    results: List[Dict[str, Any]] = []
    issue_author_cache: Dict[Tuple[str, int], Optional[str]] = {}
    pr_commits_cache: Dict[int, List[Dict[str, Any]]] = {}

    # --- Pre-fill cache with local issues to avoid extra API calls ---
    if local_issues:
        for i in local_issues:
            issue_author_cache[(f"{owner}/{repo}".lower(), i["number"])] = ((i.get("user") or {}).get("login"))

    # --- Step 1: collect all references first ---
    all_refs: Dict[int, List[Dict[str, Any]]] = {}  # PR number → list of reference dicts
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

    # --- Step 2: batch resolve unique referenced issues ---
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

    # --- Step 3: attach issue authors to each PR reference ---
    for pr_number, info in all_refs.items():
        for ref in info["links"]:
            key = (ref["referenced_repo"].lower(), ref["issue_number"])
            ref["issue_author"] = issue_author_cache.get(key)
        results.append({
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
    issue_author_cache: Dict[Tuple[str, int], Optional[str]] = {}  # (repo, issue_number) -> issue_author

    for c in commits:
        msg = ((c.get("commit") or {}).get("message")) or ""
        if not msg:
            continue

        commit_author = None
        # prefer GitHub user login if available
        if c.get("author") and isinstance(c["author"], dict):
            commit_author = c["author"].get("login")
        # fallback to commit metadata author name
        if not commit_author:
            commit_author = ((c.get("commit") or {}).get("author") or {}).get("name")

        for ref in extract_issue_refs_detailed(msg):
            if not ref["has_closing_kw"]:
                continue

            ref_repo = ref["full_repo"] or f"{owner}/{repo}"
            ref_owner, ref_name = ref_repo.split("/")
            issue_num = ref["number"]
            issue_key = (ref_repo.lower(), issue_num)

            # cache issue author to minimize API calls
            if issue_key in issue_author_cache:
                issue_author = issue_author_cache[issue_key]
            else:
                issue_data = get_issue_or_pr_details(ref_owner, ref_name, issue_num)
                issue_author = ((issue_data or {}).get("user") or {}).get("login")
                issue_author_cache[issue_key] = issue_author

            results.append({
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
    # Issues API returns both issues and PRs; PRs have 'pull_request' key.
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

    # pull regular issue comments for both issues and PRs
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

        # Extract all text sources: title, body, and comments
        for where, text, seen_at in _source_text_buckets_for_issue_like(owner, repo, source):
            if not text:
                continue

            # Find all cross-repo references (e.g. org/repo#123)
            for m in CROSS_REPO_RE.finditer(text):
                target_full = m.group(1)
                target_num = int(m.group(2))
                if target_full.lower() == this_repo_full:
                    continue  # skip same-repo references

                tgt_owner, tgt_repo = _parse_full_repo(target_full)
                cache_key = (target_full.lower(), target_num)

                # cache to avoid refetching same issue multiple times
                if cache_key in target_cache:
                    target_details = target_cache[cache_key]
                else:
                    target_details = get_issue_or_pr_details(tgt_owner, tgt_repo, target_num)
                    target_cache[cache_key] = target_details

                # Classify and extract metadata
                target_type = classify_issue_or_pr(target_details)
                target_created_at = target_details.get("created_at") or target_details.get("updated_at")
                target_url = target_details.get("html_url")
                target_author = ((target_details.get("user") or {}).get("login")) if target_details else None

                # Compose full record with timestamps
                results.append({
                    "source": {
                        "repo": f"{owner}/{repo}",
                        "type": source_type,          # "issue" | "pull_request"
                        "number": source_number,
                        "url": source_url,
                        "created_at": source_created_at,  # when source issue/PR was created
                    },
                    "reference": {
                        "found_in": where,            # "issue_title" | "issue_body" | "issue_comment"
                        "seen_at": seen_at,           # when cross-reference text appeared
                        "cross_ref_timestamp": seen_at,  # explicit alias for clarity
                    },
                    "target": {
                        "repo": target_full,
                        "type": target_type,          # "issue" | "pull_request"
                        "number": target_num,
                        "url": target_url,
                        "created_at": target_created_at,  # when target issue/PR was created
                        "author": target_author,
                    },
                })

        if len(results) % 50 == 0 and len(results) > 0:
            print(f"  found {len(results)} cross-repo references so far...")

    return results

# --- SECTION: Commit Lineage (parent SHA + blame-like approximation) ---
def get_commit_lineage(owner: str, repo: str, commits: List[Dict[str, Any]], max_files_per_commit: int = 5) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    commit_cache: Dict[str, Dict[str, Any]] = {}         
    prev_lookup_cache: Dict[Tuple[str, str], Optional[dict]] = {} 

    for idx, c in enumerate(commits, 1):
        sha = c.get("sha")
        if not sha:
            continue

        # --- reuse cached commit detail if available ---
        detail = commit_cache.get(sha)
        if not detail:
            detail = get_commit_detail(owner, repo, sha)
            if not isinstance(detail, dict):
                continue
            commit_cache[sha] = detail

        ident = _extract_identity(detail)
        parent_shas = [p.get("sha") for p in detail.get("parents", []) if p.get("sha")]
        files = detail.get("files", []) or []

        unified_files = []
        # limit expensive previous commit lookups to N files
        processed_files = 0

        for f in files:
            fname = f.get("filename")
            status = f.get("status")
            if not fname or status == "added":
                # skip added files — no previous commit to find
                unified_files.append({
                    "filename":  fname,
                    "status":    status,
                    "additions": f.get("additions"),
                    "deletions": f.get("deletions"),
                    "changes":   f.get("changes"),
                    "blob_url":  f.get("blob_url"),
                    "raw_url":   f.get("raw_url"),
                    "previous_commit": None,
                })
                continue

            prev_commit_info = None

            if parent_shas and processed_files < max_files_per_commit:
                parent_sha = parent_shas[0]
                cache_key = (parent_sha, fname)

                if cache_key in prev_lookup_cache:
                    prev_commit_info = prev_lookup_cache[cache_key]
                else:
                    # query for the previous commit touching this file
                    commits_url = f"{BASE_URL}/repos/{owner}/{repo}/commits"
                    q = f"?path={quote(fname, safe='')}&sha={parent_sha}&per_page=1"
                    resp = _request("GET", commits_url + q)
                    if resp.status_code == 200:
                        arr = resp.json()
                        if isinstance(arr, list) and arr:
                            prev = arr[0]
                            prev_commit_info = {
                                "sha": prev.get("sha"),
                                "author": ((prev.get("commit") or {}).get("author") or {}).get("name"),
                                "date":   ((prev.get("commit") or {}).get("author") or {}).get("date"),
                                "(identity function) author": ident["author"],       
                                "(identity function) committer": ident["committer"],       
                                "message": (prev.get("commit") or {}).get("message"),
                                "url": prev.get("html_url"),
                            }
                    prev_lookup_cache[cache_key] = prev_commit_info
                    processed_files += 1

            unified_files.append({
                "filename":  fname,
                "status":    status,
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
                "changes":   f.get("changes"),
                "blob_url":  f.get("blob_url"),
                "raw_url":   f.get("raw_url"),
                "previous_commit": prev_commit_info,
            })

        results.append({
            "sha": sha,
            "message": ((detail.get("commit") or {}).get("message")),
            "author":  ((detail.get("commit") or {}).get("author") or {}).get("name"),
            "(identity function) author": ident["author"],       
            "(identity function) committer": ident["committer"],       
            "date":    ((detail.get("commit") or {}).get("author") or {}).get("date"),
            "parents": parent_shas,
            "url": detail.get("html_url"),
            "files": unified_files,
        })

        if idx % 20 == 0:
            print(f"  processed {idx} commits (lineage)...  cache={len(prev_lookup_cache)}")

    return results

# --- Helpers ---
def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _extract_identity(commit_detail: Dict[str, Any]) -> Dict[str, Any]:
    gh_author = (commit_detail.get("author") or {})  # has 'login' if mapped
    gh_committer = (commit_detail.get("committer") or {})

    meta = (commit_detail.get("commit") or {})
    meta_author = (meta.get("author") or {})
    meta_committer = (meta.get("committer") or {})

    return {
        "author": {
            "login": gh_author.get("login"),
            "id": gh_author.get("id"),
            "name": meta_author.get("name"),
            "email": meta_author.get("email"),
            "date": meta_author.get("date"),
        },
        "committer": {
            "login": gh_committer.get("login"),
            "id": gh_committer.get("id"),
            "name": meta_committer.get("name"),
            "email": meta_committer.get("email"),
            "date": meta_committer.get("date"),
        }
    }

# --- Metrics ---
def summarize_metrics(
    repo_meta: Dict[str, Any],
    issues: List[Dict[str, Any]],
    prs: List[Dict[str, Any]],
    commits: List[Dict[str, Any]],
    pr_issue_links: List[Dict[str, Any]],
    cross_repo_links: List[Dict[str, Any]],
    commit_lineage: List[Dict[str, Any]],
    closed_by_commits: Optional[List[Dict[str, Any]]] = None,   # <- NEW
) -> Dict[str, Any]:
    closed_by_commits = closed_by_commits or []
    num_issues = len(issues)
    num_prs = len(prs)
    num_commits = len(commits)
    num_prs_with_links = len(pr_issue_links)
    num_cross_repo_links = len(cross_repo_links)

    # --- aggregates from lineage ---
    total_changed_files = sum(len(c.get("files", []) or []) for c in commit_lineage)
    total_additions = sum(
        sum((f.get("additions") or 0) for f in (c.get("files") or []))
        for c in commit_lineage
    )
    total_deletions = sum(
        sum((f.get("deletions") or 0) for f in (c.get("files") or []))
        for c in commit_lineage
    )

    # --- repo identity ---
    this_repo_full = f'{repo_meta.get("owner", {}).get("login")}/{repo_meta.get("name")}' if repo_meta else ""
    this_repo_lc = this_repo_full.lower()

    # --- auto-closing metrics (from PR text/commits/merge commits) ---
    auto_links_from_prs_all = sum(
        1
        for pr in pr_issue_links
        for link in pr.get("links", [])
        if link.get("would_auto_close")
    )
    auto_links_from_prs_local = sum(
        1
        for pr in pr_issue_links
        for link in pr.get("links", [])
        if link.get("would_auto_close")
        and (link.get("referenced_repo","").lower() == this_repo_lc)
    )

    # --- auto-closing from direct commits (no PR) ---
    auto_links_from_commits_all = len([x for x in closed_by_commits if x.get("would_auto_close")])
    auto_links_from_commits_local = len([
        x for x in closed_by_commits
        if x.get("would_auto_close") and x.get("referenced_repo","").lower() == this_repo_lc
    ])

    # --- unique auto-closed issues (by (repo, number)) ---
    def _pairs_from_prs():
        for pr in pr_issue_links:
            for link in pr.get("links", []):
                if link.get("would_auto_close"):
                    yield (link.get("referenced_repo"), link.get("issue_number"))

    def _pairs_from_commits():
        for x in closed_by_commits:
            if x.get("would_auto_close"):
                yield (x.get("referenced_repo"), x.get("issue_number"))

    unique_auto_closed_all = {(str(r or ""), int(n)) for (r, n) in (*_pairs_from_prs(), *_pairs_from_commits())}
    unique_auto_closed_local = {p for p in unique_auto_closed_all if (p[0] or "").lower() == this_repo_lc}

    distinct_repos = sorted({l["target"]["repo"] for l in cross_repo_links}) if cross_repo_links else []

    return {
      "repo": this_repo_full,
      "stars": repo_meta.get("stargazers_count") if repo_meta else None,
      "forks": repo_meta.get("forks_count") if repo_meta else None,
      "open_issues_count": repo_meta.get("open_issues_count") if repo_meta else None,
      "watchers": repo_meta.get("subscribers_count") if repo_meta else None,
      "counts": {
          "issues": num_issues,
          "pull_requests": num_prs,
          "commits": num_commits,
          "prs_with_issue_refs": num_prs_with_links,
          "cross_repo_issue_links": num_cross_repo_links,

          # NEW: auto-closing metrics
          "auto_closing_links_from_prs_all": auto_links_from_prs_all,
          "auto_closing_links_from_prs_local": auto_links_from_prs_local,
          "auto_closing_links_from_commits_all": auto_links_from_commits_all,
          "auto_closing_links_from_commits_local": auto_links_from_commits_local,
          "unique_issues_auto_closed_all": len(unique_auto_closed_all),
          "unique_issues_auto_closed_local": len(unique_auto_closed_local),
      },
      "diff_aggregates": {
          "total_changed_files": total_changed_files,
          "total_additions": total_additions,
          "total_deletions": total_deletions,
      },
      "cross_repo": {
          "distinct_referenced_repos": distinct_repos,
      },
      "generated_at": datetime.now(timezone.utc).isoformat(),
    }

# --- Main Orchestration ---
def process_repo(full_name: str) -> None:
    owner, repo = full_name.split("/", 1)
    out_dir = os.path.join(OUTPUT_DIR, f"{owner}_{repo}")
    ensure_dir(out_dir)

    print(f"\n=== {owner}/{repo} ===")

    # 1) Repo meta
    print("  fetching repo metadata...")
    repo_meta = get_repo_meta(owner, repo)
    save_json(f"{out_dir}/repo_meta.json", repo_meta)

    # 2) Issues
    print("  fetching issues...")
    issues = get_issues(owner, repo)
    save_json(f"{out_dir}/issues.json", issues)

    # 3) Pull Requests
    print("  fetching pull requests...")
    prs = get_pull_requests(owner, repo)
    save_json(f"{out_dir}/pull_requests.json", prs)

    # 4) Commits
    print("  fetching commits...")
    commits = get_commits(owner, repo)
    save_json(f"{out_dir}/commits.json", commits)

    # 5) PR → Issue references
    print("  fetching prs with issue references...")
    pr_links = find_prs_with_linked_issues(owner, repo, prs)
    save_json(f"{out_dir}/prs_with_linked_issues.json", pr_links)

    # 6) Issues Closed By Commits
    print("  fetching issues closed by repo commits...")
    closed_by_commits = find_issues_closed_by_repo_commits(owner, repo, commits)
    save_json(f"{out_dir}/issues_closed_by_commits.json", closed_by_commits)

    # 7) Cross-Repo references (issues + PRs) with timestamps
    print("  fetching cross-repo references (issues & PRs)...")
    cross_links = find_cross_project_links_issues_and_prs(owner, repo, issues, prs)
    save_json(f"{out_dir}/cross_repo_links.json", cross_links)

    # 8) Commit lineage
    print("  collecting commit lineage...")
    commit_lineage = get_commit_lineage(owner, repo, commits)
    save_json(f"{out_dir}/commit_lineage.json", commit_lineage)

    # 9) Summary
    summary = summarize_metrics(
        repo_meta=repo_meta,
        issues=issues,
        prs=prs,
        commits=commits,
        pr_issue_links=pr_links,
        cross_repo_links=cross_links,
        commit_lineage=commit_lineage,
        closed_by_commits=closed_by_commits,
    )
    save_json(f"{out_dir}/summary_metrics.json", summary)
    print(f"  ✅ done → {out_dir}")

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
