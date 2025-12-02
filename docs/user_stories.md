## 1) Cross-repo dependency health (cross-repo/project)

**As a** micromatch maintainer responsible for ecosystem stability  
**I want** to surface which external projects repeatedly reference micromatch issues/PRs (e.g., fast-glob, jest, chokidar) and when those references spike, so **I can** coordinate fixes and outreach before downstream breakages spread.

**Why it’s complex:** `cross_repo_links` holds nested `source`/`target` objects with timestamps and repo identifiers. For micromatch there are 45 links; top targets include `mrmlnc/fast-glob` (10) and `facebook/jest` (3), spanning both issues and PRs. Correlating these with local issue states requires joins across indices and time-bucketing.

**Acceptance criteria**

- A Kibana (or query) view that aggregates cross-repo links by `target.repo_name`, split by `source.type` (issue vs PR), with a time histogram on `reference.cross_ref_timestamp`.
- Ability to drill into a target repo (e.g., `mrmlnc/fast-glob`) to list the originating micromatch issues/PRs, their titles, and URLs, ordered by recency.
- A derived metric per target: share of references that include closing keywords vs purely informational (using `reference.found_in` + presence of `has_closing_kw` when available).
- A weekly trend alert when any target repo’s references grow >50% week-over-week.

## 2) Issue-to-PR lifecycle coverage (issues-with-pr)

**As a** triage lead planning releases  
**I want** a lifecycle view that merges issues, PRs, linked-issue metadata, and commit-based closures, so **I can** identify unaddressed issues, PRs touching multiple tickets, and commits that closed issues without a PR.

**Why it’s complex:** micromatch has 196 issues, 80 PRs, 44 PRs with linked issues (up to 8 links per PR), and 17 issues closed directly by commits. Stitching this needs `prs_with_linked_issues` (PR→issue links), `issues_closed_by_commits` (commit→issue with closing keywords), and base `issues`/`pull_requests` for state/timestamps/authors.

**Acceptance criteria**

- A consolidated table keyed by issue number with: issue state/timestamps, linked PR numbers from `prs_with_linked_issues`, commit SHAs from `issues_closed_by_commits`, and whether the issue was auto-closed vs manually closed.
- A filter to find issues with no PR links but closed by commits (silent closures), and issues still open despite PR links (possible stalled merges).
- A per-release report: count of issues resolved per release window, split by closure path (PR-linked vs commit-only), and median lead time from issue creation to first linked PR and to final closure.
- Highlight PRs that touch 3+ issues (7 such PRs in micromatch) to flag potential risk/merge coordination; show their authors and creation dates.

## ES|QL query sketches

Replace `micromatch/micromatch` with any repo; prefix indices if your cluster uses one (e.g., `gh_repo_meta` → `gh_repo_meta*`).

### Cross-repo dependency health

```esql
from cross_repo_links
| where source.repo_name == "micromatch/micromatch"
| eval week = date_trunc(1w, reference.cross_ref_timestamp)
| stats refs = count(*) by week, target_repo = target.repo_name, source_type = source.type
| sort week desc, refs desc
| limit 200
```

Drill into a target:

```esql
from cross_repo_links
| where source.repo_name == "micromatch/micromatch" and target.repo_name == "mrmlnc/fast-glob"
| keep source.type, source.number, source.url, reference.cross_ref_timestamp, target.url
| sort reference.cross_ref_timestamp desc
| limit 50
```

### Issue-to-PR lifecycle coverage

### Join-free backlog risk triage (alternate issue→PR scenario)

User story: **As a release manager**, I want to surface (a) long-open issues with no signals, (b) PRs that reference issues but remain open, and (c) issues closed by multiple commits, so I can prioritize cleanup without joins/lookup indices.

- Long-open issues (120+ days), oldest first:

```esql
from issues
| where repo_name == "micromatch/micromatch" and state == "open"
| eval age_days = date_diff("day", created_at, now())
| where age_days >= 120
| sort created_at asc
| limit 200
```

- Open PRs that reference issues (possible stalled merges):

```esql
from prs_with_linked_issues
| where repo_name == "micromatch/micromatch" and state == "open"
| mv_expand links.issue_number
| stats
    link_count = count(*),
    linked_issues = values(links.issue_number)
  by pr_number, title, author, created_at
| sort created_at asc
| limit 200
```

- Issues closed by multiple commits (possible risky hotfixes):

```esql
from issues_closed_by_commits
| where repo_name == "micromatch/micromatch"
| stats commit_count = count(*), closing_shas = values(commit_sha) by issue_number
| where commit_count >= 2
| sort commit_count desc
| limit 200
```

Find PRs that touch 3+ issues:

```esql
from prs_with_linked_issues
| where repo_name == "micromatch/micromatch"
| mv_expand links.issue_number
| stats
    link_count = count(*),
    linked_issues = values(links.issue_number)
  by pr_number, author, state, created_at
| where link_count >= 3
| sort created_at desc
| limit 200
```

### Alternate lifecycle view (no lookups; uses only `prs_with_linked_issues`)

User story: **As a release manager**, I want to spot PRs that touch multiple issues but have no closing keywords in their links, so I can ensure those issues get closed or tracked before merge.

```esql
from prs_with_linked_issues
| where repo_name == "micromatch/micromatch"
| mv_expand links.issue_number
| eval has_closing_kw = coalesce(links.has_closing_kw, false)
| stats
    issues = values(links.issue_number),
    issue_count = count_distinct(links.issue_number),
    closing_kw_any = max(has_closing_kw)
  by pr_number, author, state, created_at
| where issue_count >= 2 and closing_kw_any == false
| sort issue_count desc, created_at desc
| limit 200
```

This avoids joins/lookup indices, still highlights risky PRs (multi-issue touch, no closing keywords), and works directly on `prs_with_linked_issues`.
