# Pipeline JSON Outputs

Each time `pipeline.py` runs, it creates a folder at `output/{owner_repo}` containing a fixed set of JSON files. The notes below describe (1) what each file represents, (2) how the data is collected, and (3) what every key means in plain English so that anyone inspecting the JSON can immediately understand the contents.

---

## repo_meta.json

**What it is:** A single JSON document describing the repository itself.  
**How it is produced:** Direct result of the GitHub REST endpoint `GET /repos/{owner}/{repo}`.

- **`repo_name`** – Canonical repository name in `owner/repo` format; used everywhere else as a join key.
- **`id` / `node_id`** – Numeric (REST) and GraphQL identifiers that uniquely identify the repository.
- **`name` / `full_name`** – Short name (just the repo) versus full owner/repo string.
- **`description`** – Human-friendly overview written on the repository’s home page.
- **`homepage`** – Project website URL if the maintainers configured one.
- **`topics`** – List of GitHub “Topics” labels attached to the repo.
- **`private`** – True when the repo is private; False for public repos.
- **`fork`** – True when the repo is itself a fork of another repository.
- **`default_branch`** – Name of the branch used for new clones (usually `main` or `master`).
- **`owner`** – Nested object describing the account or organization that owns the repo (login, id, avatar, etc.).
- **`organization`** – Same structure as owner but only present when the repo belongs to an org.
- **`license`** – Nested structure describing the declared license (name, SPDX identifier, URL).
- **`permissions`** – Booleans showing what the authenticated user can do (admin, push, pull).
- **`language`** – Primary programming language detected by GitHub’s linguist analysis.
- **`created_at` / `updated_at` / `pushed_at`** – ISO timestamps showing when the repo was created, updated, and last pushed to.
- **`stargazers_count`** – Number of stars (bookmarks) from GitHub users.
- **`watchers_count`** – Mirror of stargazers (legacy field kept for compatibility).
- **`forks_count`** – Number of times other users forked the repo.
- **`open_issues_count`** – Total count of open issues and PRs.
- **`size`** – Estimated repository size reported by GitHub (in kilobytes).

---

## issues.json

**What it is:** A list of every issue in the repository (open or closed). Pull requests are filtered out so this file only contains true issue data.  
**How it is produced:** `GET /repos/{owner}/{repo}/issues?state=all`, followed by removing entries that contain the `pull_request` field.

- **`repo_name`** – Owner/repo the issue belongs to.
- **`id` / `node_id`** – REST/GraphQL identifiers for the issue.
- **`number`** – GitHub issue number (same value used in the UI, e.g., `#123`).
- **`state`** – Current status (open, closed, etc.).
- **`title` / `body`** – User-written title and description.
- **`created_at` / `updated_at` / `closed_at`** – Timestamps showing when the issue was created, last updated, and closed (if applicable).
- **`user`** – Object describing who opened the issue (login, id, avatar, etc.).
- **`assignee` / `assignees`** – One or more users currently assigned to the issue.
- **`labels`** – List of label objects attached to the issue; each includes name, color, and description.
- **`milestone`** – Milestone metadata when the issue is assigned to a milestone.
- **`comments`** – Total number of comment records on the issue.
- **`author_association`** – Relationship between the issue author and the repository (OWNER, MEMBER, CONTRIBUTOR, etc.).
- **`state_reason`** – GitHub-provided reason for the current state (e.g., completed, not_planned).
- **`active_lock_reason`** – Explanation (if any) for why conversation was locked.
- **`reactions`** – Aggregate counts for emoji reactions (👍, 👎, laugh, hooray, etc.).
- **`sub_issues_summary` / `issue_dependencies_summary`** – Optional nested structures returned when a repo uses GitHub issue forms or dependency features.

---

## pull_requests.json

**What it is:** Complete history of pull requests, including drafts and closed PRs.  
**How it is produced:** `GET /repos/{owner}/{repo}/pulls?state=all`.

- **`repo_name`** – Owner/repo the PR belongs to.
- **`id` / `node_id` / `number`** – Identifiers and the user-facing PR number.
- **`title` / `body`** – PR title and description text.
- **`state`** – Whether the PR is open or closed.
- **`locked`** – True when the PR conversation is locked (no new comments).
- **`draft`** – True when the PR is a draft (not ready for review).
- **`merged`** – True if GitHub reports the PR as merged.
- **`merge_commit_sha`** – SHA of the commit GitHub created when the PR was merged (only available for merge commits).
- **`created_at` / `updated_at` / `closed_at` / `merged_at`** – Lifecycle timestamps for PR creation, updates, closure, and merge.
- **`user`** – Account that opened the PR.
- **`assignee` / `assignees` / `requested_reviewers` / `requested_teams`** – Users or teams involved in the review process.
- **`labels` / `milestone`** – Labels and milestone attached to the PR.
- **`head` / `base`** – Nested objects describing the source (head) branch and target (base) branch; include branch name, repo info, and user.
- **`_links`** – Hypermedia links (API and HTML) provided by GitHub for navigation.
- **`author_association`** – Relationship between the PR author and the repo.
- **`auto_merge`** – Auto-merge configuration if the PR opted into GitHub’s auto-merge.

---

## commits.json

**What it is:** All commits returned by GitHub’s commits API, enriched with per-file details and statistics.  
**How it is produced:** `GET /repos/{owner}/{repo}/commits` (paginated), and for each commit, a follow-up call to `GET /repos/{owner}/{repo}/commits/{sha}` to obtain files and stats.

- **`repo_name`** – Owner/repo the commit belongs to.
- **`sha` / `node_id`** – Unique identifiers for the commit.
- **`commit`** – Nested structure from GitHub containing the raw commit data (original author and committer names/emails, timestamps, message, tree SHA, verification info).
- **`author` / `committer`** – GitHub user objects for the author and committer when they have GitHub accounts (may be `null` for anonymous authors).
- **`url` / `html_url` / `comments_url`** – API endpoint, web URL, and comments API endpoint for the commit.
- **`parents`** – Array of parent commit objects (each has a SHA and URL).
- **`files_changed`** – List of filenames that changed in the commit. Computed from the commit detail endpoint.
- **`files_changed_count`** – Integer count of filenames in `files_changed`.
- **`stats`** – Additions, deletions, and total lines changed (from the commit detail endpoint). Helps quantify churn.

---

## contributors.json

**What it is:** Snapshot of top contributors according to GitHub’s contributor statistics.  
**How it is produced:** `GET /repos/{owner}/{repo}/contributors`.

- **`repo_name`** – Owner/repo identifier.
- **`login` / `id` / `html_url`** – Account information for the contributor.
- **`type`** – Indicates if the contributor is a “User” or an “Organization”.
- **`site_admin`** – True if the account is a GitHub site admin (rare).
- **`contributions`** – Number of commits attributed to the contributor (GitHub’s default metric for this endpoint).

---

## prs_with_linked_issues.json

**What it is:** Derived dataset showing which PRs mention issues in their text or commit history, and whether those mentions would automatically close the issue when merged.  
**How it is produced:** For every PR, the pipeline scans the PR title/body, all commits in the PR, and the merge commit message (if available). It extracts references such as `fixes #123` or `owner/repo#456`.

- **`repo_name`** – Owner/repo for the PR.
- **`pr_number`** – Pull request number.
- **`title`** – PR title text.
- **`author`** – Login of the PR author.
- **`state`** – Current PR state (open/closed).
- **`merged`** – Boolean indicating whether the PR has been merged.
- **`created_at`** – Timestamp when the PR was opened.
- **`url`** – HTML URL linking to the PR on GitHub.
- **`links`** – Array describing each issue mention:
  - **`referenced_repo`** – Owner/repo containing the referenced issue. Defaults to the same repo when the PR references `#123`.
  - **`issue_number`** – Numeric issue number.
  - **`reference_type`** – Indicates where the mention was found: `"pr_text"`, `"commit_message"`, or `"merge_commit_message"`.
  - **`has_closing_kw`** – True if the text included closing keywords such as “fixes”, “closes”, or “resolves”.
  - **`would_auto_close`** – True when the PR is merged and also has a closing keyword; mirrors GitHub’s auto-close behavior.
  - **`issue_author`** – Login of the issue’s author (fetched on demand and cached).

---

## issues_closed_by_commits.json

**What it is:** Derived dataset listing commits in the repository that include closing keywords referencing issues. This helps explain why an issue was closed without a PR.  
**How it is produced:** Every commit message is scanned for references like “fixes #123” or “owner/repo#456”. Only references with closing keywords are included.

- **`repo_name`** – Owner/repo containing the commit.
- **`commit_sha`** – SHA of the commit that mentions the issue.
- **`commit_url`** – HTML URL for the commit.
- **`commit_author`** – Login or name of the commit author (prefers GitHub login when available).
- **`referenced_repo`** – Owner/repo of the referenced issue.
- **`issue_number`** – Issue number referenced in the commit message.
- **`issue_author`** – Login of the referenced issue’s author (fetched via REST and cached).
- **`reference_type`** – Currently always `"commit_message"` because only commit message references are tracked here.
- **`has_closing_kw`** – Always True (only closing references are stored).
- **`would_auto_close`** – True when GitHub would auto-close the referenced issue upon merging/pushing the commit.

---

## cross_repo_links.json

**What it is:** Catalog of cross-repository references discovered in issue or PR text/timeline events. This reveals when one project references another (e.g., `other-org/other-repo#123`).  
**How it is produced:** The pipeline scans issue titles, bodies, and PR equivalents for patterns like `owner/repo#number`. It also follows GitHub timeline events for cross-reference notifications.

- **`source`** – Describes the artifact containing the reference:
  - **`repo_name`** – Owner/repo where the reference was found.
  - **`type`** – Whether the source is an “issue” or a “pull_request”.
  - **`number`** – Issue or PR number.
  - **`url`** – HTML URL for the source artifact.
  - **`created_at`** – Timestamp when the source artifact was created (or last updated if creation time unavailable).
- **`reference`** – Context detailing how the reference was observed:
  - **`found_in`** – Which text bucket contained the mention (“issue_title” or “issue_body”).
  - **`seen_at`** – Timestamp when the pipeline detected the reference.
  - **`cross_ref_timestamp`** – Duplicate of `seen_at` (simplifies Elasticsearch range queries).
- **`target`** – Metadata about the referenced issue/PR:
  - **`repo_name`** – Owner/repo of the referenced artifact.
  - **`type`** – “issue” or “pull_request”, determined by inspecting the fetched document.
  - **`number`** – Target issue/PR number.
  - **`url`** – HTML URL for the target.
  - **`created_at`** – Target creation timestamp (or last update).
  - **`author`** – Login of the target’s author.

---

## repo_blame.json

**What it is:** Snapshot summarizing git blame attribution for repository files. It shows which authors are responsible for which line ranges.  
**How it is produced:** Uses the GitHub GraphQL blame API (`BLAME_QUERY_BY_REF` first, falling back to `BLAME_QUERY_BY_OBJECT`). For each tracked file, the pipeline records blame ranges, enriches them with commit data, and extracts representative examples.

- **`repo_name`** – Owner/repo for the snapshot.
- **`ref`** – Branch name or qualified ref used when collecting blame.
- **`generated_at`** – Timestamp (UTC) indicating when the blame snapshot was generated.
- **`error`** – When present, explains why blame couldn’t be collected (e.g., missing tokens).
- **`files`** – Array describing each file processed:
  - **`path`** – File path relative to the repository root.
  - **`ref`** – Branch/ref used for this file’s blame (mirrors top-level ref).
  - **`root_commit_oid`** – Commit SHA GitHub identifies as the root for the blame data (useful for tracking stale files).
  - **`ranges_count`** – Number of blame ranges GitHub returned.
  - **`total_lines`** – Total number of lines covered by blame ranges.
  - **`authors`** – Aggregated attribution data:
    - **`author`** – Login/name (from the commit’s author info).
    - **`total_lines`** – Number of lines attributed to this author for the file.
    - **`ranges`** – Detailed slices for this author:
      - **`start` / `end` / `count`** – Line numbers and length of the range.
      - **`age`** – Age indicator provided by GitHub (relative age of the lines).
      - **`commit_sha`** – Commit hash responsible for the range.
      - **`committed_date`** – Timestamp when the commit was authored.
      - **`message`** – First line of the commit message for quick context.
      - **`matching_commit`** – Nested summary tying the blame range back to the enriched commit dataset:
        - **`repo_name`** – Owner/repo of the commit (usually the same repo).
        - **`sha`** – Commit hash.
        - **`html_url`** – Web link to the commit.
        - **`author_login`** – GitHub login for the commit author.
        - **`commit_author`** – Original author object from GitHub’s REST API (includes name/email).
        - **`files_changed`** – List of files changed in that commit.
        - **`files_changed_count`** – Count of files changed in that commit.
  - **`examples`** – Representative ranges (limited by `BLAME_EXAMPLE_LIMIT`) to highlight interesting sections:
    - **`lines`** – Object with start/end/count for the snippet.
    - **`commit_sha` / `committed_date` / `who` / `message`** – Quick summary of the author, time, and message for the example lines.
    - **`matching_commit`** – Same enrichment structure as the ranges above for easy navigation.

---

## Common Guarantees Across All Files

1. **`repo_name` is always present** – Every document carries `repo_name` so data can be filtered or joined regardless of file.
2. **Fields mirror GitHub unless enriched** – The pipeline preserves GitHub’s field names and shapes; any additional fields (such as `files_changed` or `matching_commit`) are clearly additive.
3. **Delivered in original order** – Arrays keep the ordering supplied by GitHub, enabling reproducible timelines and comparisons.
4. **Data provenance is obvious** – Each section above states exactly which API endpoint or derived logic produced the records, eliminating ambiguity when analyzing the JSON.
