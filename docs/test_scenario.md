# ES|QL Manual Test Scenarios (micromatch/micromatch)

These scenarios manually validate that Elasticsearch is correctly indexing and joining the GitHub data produced by the pipeline. All truths below are computed directly from the JSON in `output/micromatch_micromatch/*.json` as of this snapshot.

Unless stated otherwise, use `repo_name == "micromatch/micromatch"` in your filters.

---

## Scenario 1 – Basic issue counts

- **Goal:** Validate that the `issues` index is populated and filterable by `state`.
- **Question:** How many issues are open vs closed for `micromatch/micromatch`?
- **Truth:** 196 total issues; **33 open**, **163 closed**.
- **GitHub Verification:** https://github.com/micromatch/micromatch/issues
- **Suggested ES|QL:**

```esql
FROM issues
| WHERE repo_name == "micromatch/micromatch"
| STATS
    total  = COUNT(*),
    open   = SUM(CASE(state == "open",   1, 0)),
    closed = SUM(CASE(state == "closed", 1, 0))
```

---

## Scenario 2 – Issue comments for a specific ticket

- **Goal:** Confirm that per-issue comment counts come through correctly.
- **Question:** For issue `#25` (`"re-organize tests"`), how many comments are recorded?
- **Truth:** Issue `#25` has **1** comment (`comments == 1`).
- **GitHub Verification:** https://github.com/micromatch/micromatch/issues/25
- **Suggested ES|QL:**

```esql
FROM issues
| WHERE repo_name == "micromatch/micromatch" AND number == 25
| KEEP number, title, comments
```

---

## Scenario 3 – Distinct issue authors

- **Goal:** Validate aggregation on nested user fields in the `issues` index.
- **Question:** How many distinct GitHub users have opened issues?
- **Truth:** **141** distinct issue authors (`user.login` values).
- **GitHub Verification:** cannot find on GitHub
- **Suggested ES|QL:**

```esql
FROM issues
| WHERE repo_name == "micromatch/micromatch"
| STATS distinct_authors = COUNT_DISTINCT(user.login)
```

---

## Scenario 4 – Find the PR that fixes a bug

This mirrors “Identify the PR id that fixed Bug report (#34) in project A”, using a real bug issue.

- **Goal:** Validate that `prs_with_linked_issues` is correctly indexed and that issue links are queryable.
- **Question:** Which PR references bug-labeled issue `#155`?
- **Truth:** Issue `#155` is linked from **PR #156**.
- **GitHub Verification:** https://github.com/micromatch/micromatch/pull/156
- **Suggested ES|QL:**

```esql
FROM prs_with_linked_issues
| WHERE repo_name == "micromatch/micromatch"
| MV_EXPAND links.issue_number
| WHERE links.issue_number == 155
| KEEP pr_number, title, author, state, links.issue_number
```

---

## Scenario 5 – Issues closed directly by commits

- **Goal:** Validate the `issues_closed_by_commits` index and multi-commit closures.
- **Question:** For issue `#133`, how many commits reference it with closing keywords, and what are their SHAs?
- **GitHub Verification:** https://github.com/micromatch/micromatch/issues/133
- **Truth:** Issue `#133` is referenced by **2** commits with SHAs:
  - `677f1272cbff935983668561396076771b2a165b`
  - `f4c3f8b2265d85d613cf4b9912e00b480c87be44`
- **Suggested ES|QL:**

```esql
FROM issues_closed_by_commits
| WHERE repo_name == "micromatch/micromatch" AND issue_number == 133
| KEEP issue_number, commit_sha, commit_author, has_closing_kw, would_auto_close
```

---

## Scenario 6 – Cross-repo dependency hotspots

This mirrors “Identify which external projects depend on Project A the most”.

- **Goal:** Validate indexing of `cross_repo_links` and aggregations on nested `target.repo_name`.
- **Question:** Which external repo receives the most cross-repo references from `micromatch/micromatch`, and how many?
- **Truth:** There are **24** cross-repo links in total. The top target is **`mrmlnc/fast-glob` with 9 links**.
- **GitHub Verification:** https://github.com/micromatch/micromatch/pulls?q=mrmlnc%2Ffast-glob & https://github.com/micromatch/micromatch/issues?q=mrmlnc%2Ffast-glob
- **Suggested ES|QL:**

```esql
FROM cross_repo_links
| WHERE source.repo_name == "micromatch/micromatch"
| STATS refs = COUNT(*) BY target_repo = target.repo_name
| SORT refs DESC
```

---

## Scenario 7 – Repository commit history range

- **Goal:** Validate that the `commits` index is present and timestamps are correctly parsed.
- **Question:** What are the earliest and latest commit timestamps in the dataset, and their SHAs?
- **Truth:**
  - Earliest commit: SHA `ef90d5e3f671a1ff049d79a7ab1ef7144eb3ca37` at `2014-12-01T03:50:58Z`.
  - Latest commit: SHA `8bd704ec0d9894693d35da425d827819916be920` at `2024-08-23T16:24:18Z`.
- **GitHub Verification:** https://github.com/micromatch/micromatch/commits/master/
- **Suggested ES|QL:**

```esql
FROM commits
| WHERE repo_name == "micromatch/micromatch"
| EVAL authored_at = commit.author.date
| STATS
    first_time = MIN(authored_at),
    last_time  = MAX(authored_at)
```

You can then filter back on `authored_at == first_time` / `last_time` (or sort) to retrieve the corresponding SHAs and verify they match the truth above.

---

## Scenario 8 – Simplified cross-repo dependency health

- **Goal:** Check that you can see, for each target repo, how many links come from issues vs pull requests.
- **Questions:**
  - For each `target.repo_name`, how many links come from issues and how many from pull requests?
  - Specifically for `mrmlnc/fast-glob`, how many issue links vs PR links are there?
- **Truth:** For `mrmlnc/fast-glob` there are **10** links total: **8** from issues and **2** from pull requests.
- **GitHub Verification:** cannot find on GitHub
- **Suggested ES|QL:**

```esql
FROM cross_repo_links
| WHERE source.repo_name == "micromatch/micromatch"
| STATS
    total_links  = COUNT(*),
    issue_links  = SUM(CASE(source.type == "issue",         1, 0)),
    pr_links     = SUM(CASE(source.type == "pull_request",  1, 0))
  BY target_repo = target.repo_name
| SORT total_links DESC
```

Use the row where `target_repo == "mrmlnc/fast-glob"` to confirm the truth.

---

## Scenario 9 – Simplified issue-to-PR lifecycle coverage

- **Goal:** Summarize how many issues participate in PR links and/or commit-based closures.
- **Questions:**
  - How many **distinct issues** have at least one linked PR?
  - How many **distinct issues** appear in `issues_closed_by_commits`?
- **Truth:**
  - **51** distinct issues have at least one linked PR (`prs_with_linked_issues`).
  - **14** distinct issues appear in `issues_closed_by_commits`.
- **GitHub Verification:** unsure how to find on GitHub
- **Suggested ES|QL (linked issues):**

```esql
FROM prs_with_linked_issues
| WHERE repo_name == "micromatch/micromatch"
| MV_EXPAND links.issue_number
| STATS linked_issue_count = COUNT_DISTINCT(links.issue_number)
```

- **Suggested ES|QL (issues closed by commits):**

```esql
FROM issues_closed_by_commits
| WHERE repo_name == "micromatch/micromatch"
| STATS commit_closed_issue_count = COUNT_DISTINCT(issue_number)
```
