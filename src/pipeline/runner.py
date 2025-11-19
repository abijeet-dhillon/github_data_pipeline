"""Entry points for running the modular GitHub data pipeline."""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from .collectors import (
    collect_repo_blame,
    ensure_dir,
    get_commits,
    get_contributors,
    get_issues,
    get_pull_requests,
    get_repo_meta,
    save_json,
)
from .config import OUTPUT_DIR, REPOS
from .linkers import (
    find_cross_project_links_issues_and_prs,
    find_issues_closed_by_repo_commits,
    find_prs_with_linked_issues,
)


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
    save_json(f"{out_dir}/commits.json", commits)

    print("  fetching git blame snapshots...")
    repo_blame = collect_repo_blame(owner, repo, repo_meta, commits)
    save_json(f"{out_dir}/repo_blame.json", repo_blame)

    print("  fetching prs with issue references...")
    pr_links = find_prs_with_linked_issues(owner, repo, prs, issues)
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
    for repo in repos:
        try:
            process_repo(repo.strip())
        except Exception as exc:
            print(f"[error] {repo}: {exc}")
    print("\nAll repositories processed.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main([arg for arg in sys.argv[1:] if "/" in arg])
    else:
        main()
