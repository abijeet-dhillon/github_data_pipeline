# GitHub Data Pipeline – COSC 448

## Overview

This repository contains a developer-focused pipeline for mining GitHub repositories using the **GitHub REST API v3**.  
It automates large-scale retrieval of repository activity, relationships, and code-level history and unifies previously separate steps for metadata retrieval, issues and pull requests, commit lineage, and cross-repository link detection into one reproducible workflow.

## Key Features

- **Unified pipeline (`initial_pipeline.py`)** that orchestrates end-to-end data collection for one or more repositories.
- **Robust REST integration** with authenticated requests, pagination, rate-limit detection, exponential backoff, and retries.
- **Comprehensive coverage:** metadata, issues, pull requests, commits, file diffs, lineage, and cross-repository references.
- **Commit-level detail:** SHAs, parent SHAs, file stats (additions, deletions, changes), patches, and commit URLs.
- **PR–Issue linkage detection:** identifies `closes`, `fixes`, and `resolves` references in PRs and commits.
- **Cross-repo graph building:** extracts `org/repo#number` mentions and records timestamps for when links were created.
- **Standardized per-repo outputs** in `/output/`, ready for downstream analysis or indexing (e.g., Elasticsearch).

## Output Structure

Each processed repository produces a folder under `/output/<owner>__<repo>/` with:

| File                            | Description                                               |
| ------------------------------- | --------------------------------------------------------- |
| `repo_meta.json`                | Repository metadata (stars, forks, watchers, open issues) |
| `issues.json`                   | All issues with state, labels, comments, timestamps       |
| `pull_requests.json`            | PRs with merge state, authors, reviewers, diffs overview  |
| `commits.json`                  | Commit metadata (SHA, author, message, date)              |
| `commit_lineage.json`           | Parent-child commit relationships and file-level diffs    |
| `prs_with_linked_issues.json`   | PRs referencing issues via keywords (e.g., `closes #123`) |
| `issues_closed_by_commits.json` | Issues closed directly by commit messages                 |
| `cross_repo_links.json`         | Cross-repository references with creation timestamps      |
| `summary_metrics.json`          | Aggregated metrics summarizing repository activity        |

**Additional details**

- `commit_lineage.json` includes parent SHAs and links consistent with parent relationships visible on GitHub.
- `cross_repo_links.json` includes three timestamps: source created, target created, and when the reference occurred.

## How It Works

1. **Repository metadata** is fetched first.
2. **Issues, pull requests, and commits** are retrieved via paginated REST calls.
3. **Commit lineage and file diffs** are derived from `/repos/{owner}/{repo}/commits/{sha}` responses.
4. **Cross-repository references** are detected by scanning issue/PR text and timeline events for `org/repo#number` or URLs.
5. **Structured JSON** is written to `/output/` for each repository, producing a reproducible dataset.

## Setup & Configuration

1. **Python**: Use Python 3.10+ and a virtual environment.
2. **Dependencies**: Install requirements (e.g., `requests`) as specified in `requirements.txt`.
3. **Authentication**: Provide a GitHub Personal Access Token (classic or fine-grained) with `repo` read scope.
   - Environment variable example:
     ```bash
     export GITHUB_TOKEN="ghp_XXXXXXXXXXXXXXXXXXXXXXXXXXXX"
     ```
4. **Run**:
   ```bash
   python3 initial_pipeline.py
   ```
