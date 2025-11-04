# Individual progress update

In this report the student should write their progress update. Please organize your report each week based on: (1) Completed task, (2) In progress tasks, and (3) To do tasks.

### Table of Contents

- [Week 1](#cosc-448---tasks-week-1)
- [Week 2](#cosc-448---tasks-week-2)
- [Week 3](#cosc-448---tasks-week-3)
- [Week 4](#cosc-448---tasks-week-4)
- [Week 5](#cosc-448---tasks-week-5)
- [Week 6](#cosc-448---tasks-week-6)
- [Week 7](#cosc-448---tasks-week-7)
- [Week 8](#cosc-448---tasks-week-8)
- [Week 9](#cosc-448---tasks-week-9)

---

# COSC 448 - Tasks (Week 9)

## Action Items

- [x] Research and see if we can add git blame functionality to see who touches the file to rest_pipeline.py.
- [x] Refine rest_pipeline.py to include repo_name in each entry of each json file so there is a universal indicator for each entry to search and to cycle through GH API tokens when rate limits are hit.
- [x] Create tests for rest_pipeline.py (aim for greater than 90% test coverage).
- [x] Verify data pulled from rest_pipeline.py.
- [x] Update the python file used to index the data into elasticsearch following the new schema from rest_pipeline.py.

# COSC 448 - Summary (Week 9)

**[GitHub Data Pipeline Repository](https://github.com/abijeet-dhillon/github_data_pipeline/tree/main)**

### 1. **Overview of the `rest_pipeline.py` script**

- This script serves as a unified GitHub data pipeline that automates the retrieval and linking of repository data using the **GitHub REST API (v3)**.
- It integrates functionality for metadata retrieval, issues, pull requests, commits, and cross-repository relationship detection into a single, reproducible workflow.
- The pipeline generates structured JSON outputs for each repository under the `output/{owner_repo}/` directory, forming the foundation for later analytics and Elasticsearch indexing.
- Each record now includes a `repo_name` field to enable consistent linkage and searchability across all data sources and indices.

### 2. **How the pipeline pulls data**

- Utilizes a shared `requests.Session` with appropriate authentication headers and a rotating list of **GitHub API tokens** to avoid hitting rate limits.
- The `_request()` function features exponential backoff, retry logic, and detection of abuse-detection cooldowns (e.g., `403` and `429` headers).
- Data is pulled in a consistent sequence: repository metadata → issues → pull requests → commits → issue-PR references → commit lineage → summary metrics.
- All data is cached and written incrementally, minimizing redundant API calls while maintaining reliability and transparency in API usage.

### 3. **Enhancements added during Week 9**

- Added **Git blame integration research** (`blame_sample.py`) to identify which contributors most frequently modify a given file.
- Updated `rest_pipeline.py` so every record includes a `repo_name` key for unified indexing and cross-referencing.
- Implemented **token cycling** logic to seamlessly rotate GitHub tokens when the rate limit is reached, ensuring uninterrupted long-running retrieval.
- Enhanced validation and verification of pulled data through automated consistency checks and schema updates prior to indexing.

### 4. **Testing and verification**

- The `test_pipeline.py` file introduces a **comprehensive Pytest suite** with over 30 unit tests covering API behavior, error handling, pagination, and retry scenarios.
- Tests simulate 401/403/429 responses to confirm the reliability of the `_request()` backoff logic and validate token rotation behavior.
- Achieved approximately **85–90 % test coverage**, with strong validation across ingestion and request layers.
- Output verification confirms that the generated JSON files (`repo_meta.json`, `issues.json`, `pull_requests.json`, etc.) adhere to the expected schema and include all universal identifiers.

### 5. **Indexing and integration with Elasticsearch**

- The `index_elasticsearch.py` script (reworked in Week 9) indexes the JSON outputs into Elasticsearch.
- It automatically creates or updates indices such as `commits`, `issues`, `pull_requests`, `issues_closed_by_commits`, and `cross_repo_links`.
- Built-in schema validation ensures that data consistency from the retrieval phase carries over to the indexing phase.
- Authentication and connection parameters are configurable through constants or environment variables, aligning with local Docker-based Elastic setups.

### 6. **Verification of system workflow**

- Running the end-to-end workflow now involves:
  1. Collecting data using `rest_pipeline.py`
  2. Starting Elasticsearch locally (`docker compose up -d`)
  3. Indexing results with `index_elasticsearch.py`
  4. Inspecting visualizations in **Kibana**
- This reproducible process ensures that data moves smoothly from GitHub retrieval to searchable indices, enabling advanced analytics through dashboards and scripts.

### 7. **Summary**

- Week 9 focused on **stability, schema unification, and test coverage** improvements across the pipeline.
- The system is now resilient to rate limits, consistent in its record structure, and supported by a strong verification layer.
- These updates collectively make the COSC 448 GitHub Data Pipeline production-ready for large-scale academic and analytical use cases.

---

# COSC 448 - Tasks (Week 8)

## Action Items

- [x] Build an initial data pipeline script using all of the information gathered in the previous weeks to pull all data for a single repository.

# COSC 448 - Summary (Week 8)

### 1. **Overview of the initial_pipeline.py script**

- This script serves as a unified pipeline that automates data collection from the GitHub REST API (v3) for software repositories.
- It combines functionalities from multiple scripts, including repository metadata retrieval, issue and pull request collection, commit analysis, and cross-repository relationship detection.
- Its goal is to produce a full dataset describing a repository’s activity, relationships, and development history in a structured, JSON-based format suitable for later analysis.
- Each repository processed generates its own folder under the `output/` directory with a consistent set of JSON outputs.

### 2. **How the pipeline pulls data**

- Uses a global `requests.Session` with proper headers and authentication (`Authorization: token ...`) to handle all API requests efficiently.
- Each data type—issues, PRs, commits, and metadata—is retrieved using paginated GET requests that automatically iterate through all available pages.
- The `_request()` function implements rate-limit detection, exponential backoff, and retry handling for reliability under GitHub’s API constraints.
- Data is fetched sequentially in this order: repository metadata → issues → pull requests → commits → cross-references → commit lineage → summary.
- Intermediate results are cached in memory (e.g., issue authors, commit details) to minimize redundant API calls.

### 3. **What data the pipeline outputs**

For each repository, the pipeline produces a folder under `/output/` with the following files:

| Output File                     | Description                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------ |
| `repo_meta.json`                | Repository-level metadata (stars, forks, watchers, open issues)                |
| `issues.json`                   | All issues in the repository (open and closed)                                 |
| `pull_requests.json`            | All pull requests, including merged and unmerged                               |
| `commits.json`                  | Commit metadata (SHA, author, message)                                         |
| `prs_with_linked_issues.json`   | PRs that reference issues using keywords like “closes”, “fixes”, or “resolves” |
| `issues_closed_by_commits.json` | Issues closed directly by commit messages (without a PR)                       |
| `cross_repo_links.json`         | Cross-project references found in issue bodies, PRs, or comments               |
| `commit_lineage.json`           | Each commit’s parent SHA and file-level change lineage                         |
| `summary_metrics.json`          | Aggregated metrics summarizing repository activity and relationships           |

### 4. **Key processing components**

- **PR–Issue Linking:** Detects references to issues inside PR titles, descriptions, and commit messages, identifying which PRs would automatically close issues when merged.
- **Cross-Project Linking:** Parses issues and PRs for mentions of other repositories using the `org/repo#number` format, mapping inter-repo relationships.
- **Commit Lineage Tracking:** Collects parent commit SHAs and retrieves file-level diffs (additions, deletions, and previous commits touching the same file).
- **Metrics Summary:** Aggregates repository-wide counts, diff statistics, and linkage metrics into a single summary file.

### 5. **Benefits of this approach**

- **Automation:** The pipeline can process multiple repositories in one run with minimal manual setup.
- **Reliability:** Built-in rate-limit and retry logic ensures uninterrupted execution even on large repositories.
- **Completeness:** Combines multiple GitHub data domains (issues, PRs, commits, and references) into a unified structure.
- **Reproducibility:** Every run produces standardized JSON output for analysis or database ingestion.
- **Scalability:** Easily extended to additional repositories, or adapted for GitHub’s GraphQL API for improved efficiency.

### 6. **Insights enabled by this pipeline**

- Identifies how issues, PRs, and commits are connected within and across repositories.
- Enables analysis of code churn (additions/deletions) and contributor behavior.
- Maps inter-project dependencies and collaboration networks through cross-references.
- Facilitates research on software evolution, development workflows, and contribution dynamics.

### 7. **Summary**

- The `initial_pipeline.py` script transforms raw GitHub REST API data into structured JSON files capturing issues, PRs, commits, diffs, and inter-repository relationships.
- It creates a reliable and extensible foundation for empirical analysis of software projects, supporting advanced metrics and cross-repository research.
- This approach provides transparency, reproducibility, and scalability for data-driven studies of open-source software development.

### 8. **Additional Information**

- The `commit_lineage.json` file now includes **parent SHAs and commit links** that match the **parent relationships visible on GitHub’s website**, allowing for more accurate lineage tracking.
- The `cross_repo_links.json` file includes **timestamps** for when each cross-repository relationship occurred:
  - **Source created:** When the referencing issue or PR was created.
  - **Target created:** When the referenced issue or PR was created.
  - **Reference timestamp:** When the cross-reference was made in text (issue body, PR body, or comment).

---

# COSC 448 - Tasks (Week 7)

## Action Items

- [x] Explore how to get a commit’s SHA and diff, to see the files changed in the commit/code.
- [x] Explore how to query cross-project issue relationships (issues referencing other repositories.

# COSC 448 - Summary (Week 7)

### 1. **Explore how to get a commit’s SHA and diff, to see the files changed in the commit/code (see commit_diff_retrieval.py file):**

- The GitHub REST API provides the endpoint GET /repos/{owner}/{repo}/commits to retrieve a list of commits from a repository, each containing a unique SHA identifier.
- The SHA acts as a reference to a specific commit and can be used to access further details about that commit.
- To view the exact code changes, the endpoint GET /repos/{owner}/{repo}/commits/{sha} returns detailed metadata, including which files were modified, added, or deleted.
- This same endpoint also includes line-level changes (additions and deletions) and can return patch data showing the differences within each file.
- By combining these endpoints, one can identify a commit by its SHA and retrieve its full diff to analyze how the code or documentation changed.

### 2. **Explore how to query cross-project issue relationships (issues referencing other repositories) (see cross_project_issue_links.py file):**

- The GitHub REST API exposes issue data through GET /repos/{owner}/{repo}/issues, which includes fields like body, timeline_url, and pull_request that can reference other repositories.
- Cross-repository links occur when an issue description, comment, or event contains a URL to another repo’s issue or pull request (e.g., https://github.com/otherOrg/otherRepo/issues/42).
- To detect these relationships, the Issues Timeline API (GET /repos/{owner}/{repo}/issues/{issue_number}/timeline) can be queried to view “cross-referenced” events — these are automatically generated when an issue or PR in one repository mentions another by URL or owner/repo#number syntax.
- By parsing cross-referenced events in the timeline data, one can identify which external repository or issue created the reference and when it occurred.
- Therefore, analyzing these timeline events across multiple repositories allows you to map relationships between issues — for example, linking a bug report in one project to a pull request or dependency issue in another.

---

# COSC 448 - Tasks (Week 6)

## Action Items

- [x] Determine how to view raw data directly in Elasticsearch.
- [x] Identify whether closed issues linked to merged pull requests can be detected.
- [x] Check if open issues have associated PRs (merged / failed / not merged).
- [x] Review the GitHub Events and GitHub Issues APIs (e.g. can we see when a user self-assigns an issue).
- [x] Confirm if we can retrieve source code, commit IDs, and PR details via the API.
- [x] Explore how to query cross-project issue relationships (e.g., issues referencing events in other repositories).
- [x] Use npm packages Tanner provided to use for data pulling (with tmux, thanks Anubhav)

# COSC 448 - Summary (Week 6)

### 1. **Determine how to view raw data directly in Elasticsearch**

- Started the local Elasticsearch instance using Docker (cd elastic-start-local && docker compose up -d).
- Opened Kibana at http://localhost:5601, navigated to Discover, and viewed indices such as github_issues and github_pull_requests.
- Examined raw JSON documents, which represent individual indexed records — each document corresponds to one issue, PR, commit, or contributor entry with structured fields (e.g., title, state, repo).
- Clarified that these differ from the raw data .json files created by v3_data_retrieval.py; the files are full API exports, whereas the indexed documents are searchable records in Elasticsearch.
- Seeing 30,975 documents means 30,975 individual GitHub records were successfully indexed — each document acts like one “row” in a searchable database.

### 2. **Identify whether closed issues linked to merged pull requests can be detected**

- Implemented the query function find_prs_with_linked_issues() in query_elasticsearch.py.
- The function scans all PRs in github_pull_requests for references such as #<issue_number> within titles or bodies.
- Joins those PRs to matching issues in the github_issues index by number.
- Returns both the PR state (merged, open, closed) and the linked issue state (open / closed).
- Results are saved to query_output/prs_with_linked_issues.txt for review.
- Verified that closed issues linked to merged PRs can indeed be detected when PR text includes keywords like closes or fixes #<issue>.

### 3. **Check if open issues have associated PRs (merged / failed / not merged)**

- Re-used the same query function (find_prs_with_linked_issues()) to evaluate all PR–issue pairs, independent of state.
- For each issue referenced in a PR, retrieved both the PR and issue states to compare status relationships.
- Output lists PRs marked as open, closed, or merged alongside the linked issue’s state.
- Identifies open issues with active PRs, failed merges, or unmerged states.
- Example output: PR State: open | Merged: False | Issue State: open (stored in .txt output file).
- Confirms ability to detect open issues that already have associated PRs in any merge state.

### 4. **Review the GitHub Events and Issues APIs (e.g., detect self-assignment events)**

- Explored Issues → Issue Events endpoint (GET /repos/{owner}/{repo}/issues/{issue_number}/events) and repo-level variant (.../issues/events).
- Located events with event: "assigned"; payload includes assignee (who was assigned) and assigner/actor (who performed the assignment).
- A self-assign is identified when assignee.login == assigner.login; fallback check compares to actor.login if assigner is missing.
- For richer context (labels, cross-refs, comments, etc.), used the Issue Timeline endpoint (GET /repos/{owner}/{repo}/issues/{issue_number}/timeline).
- Scripted iteration through issues to classify events as SELF-ASSIGN or ASSIGNED-BY-OTHER, recording timestamps and URLs.

### 5. **Confirm if we can retrieve source code, commit IDs, and PR details via the API**

- Commit IDs (SHAs): already retrieved via the Commits endpoint in v3_data_retrieval.py; includes commit message, author/committer, date, and stats (additions/deletions/files changed).
- Pull Request details: fully captured (number, title, body, state, timestamps, merge flags, merge SHA, file stats, labels, assignees, reviewers, comments, URLs).
- Source code (not currently fetched):
  - Use Contents API GET /repos/{owner}/{repo}/contents/{path} to fetch specific files (Base64 encoded).
  - Or use Git Database API GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1 followed by GET /git/blobs/{blob_sha} for raw file contents.

### 6. **Explore how to query cross-project issue relationships (issues referencing other repositories)**

- Incoming links (other repos → this repo): fetched each issue’s timeline and looked for event == "cross-referenced" where source.issue.repository_url points to a different repository.
- Outgoing links (this repo → other repos): scanned issue and PR titles/bodies for patterns like owner/repo#123, keeping references where owner/repo ≠ the current repo.
- Each link is stored as a directed edge record (from_repo, from_number, from_type) → (to_repo, to_number, via, created_at, URLs).
- Thought for an index structure: github_issue_links in Elasticsearch for cross-repo visualization and aggregation.

---

# COSC 448 - Tasks (Week 5)

## Action Items

- Collect raw data
  - [x] Pull GitHub data (issues, commits, PRs, metadata) for 15 repositories using API v3.
  - [x] Review JSON structure and brainstorm ingestion strategies.
  - [ ] Use npm packages Tanner provides to use for data pulling.
- Ingest data into Elasticsearch
  - [x] Set up/test ingestion into a local Elasticsearch instance.
  - [x] Try to use different types of index structures (e.g. separate indexes for repos, issues, commits, etc., 1 index per project repo, 1 index for whole project, etc.)
  - [x] Define index mappings (look at GrimoireLab + LFx for inspiration).
  - [x] Explore Compute Canada server resources + potential dockerization.
- Formulate test queries
  - [x] Build queries on indexed data .
  - [x] Skip production-level queries for now — only exploratory.
  - [x] Validate whether indexing strategy supports useful queries.

## GitHub API Data to Extract

- **Repositories** → creation date, forked or not, org, username, stars, about/description, watchers, releases (date, version, count), contributors, number of files (proxy for differences), reactions, topics
- **Commits** → author, committer, delta (LOC added/removed/changed)
- **Pull Requests** → authors, reviewers, comments, # contributors not reviewers, member roles, creation time, status, changes requested, timestamps, event info, merge comment, GitHub Actions, etc.
- **Issues** → issue → PR linkage, comments, contributors
- **Contributors** → all available contributor metadata

## References & Resources

- **GitHub API v3 Docs:** https://docs.github.com/en/rest
- **Elasticsearch Documentation:** https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html
- **GrimoireLab Documentation: **https://chaoss.github.io/grimoirelab/
- **LFx Insights Overview:** https://lfx.linuxfoundation.org/tools/insights/
- **Docker Docs:** https://docs.docker.com/
- **Compute Canada Resources:** https://docs.alliancecan.ca/wiki/Technical_documentation

# COSC 448 – Summary (Week 5)

## Collect Raw Data

### 1. **Pull GitHub data for 15 repositories (API v3)**

- Used a Python script with the GitHub REST API v3 to collect issues, commits, pull requests, contributors, and metadata from a planned set of 15 npm package repositories (rollup, prettier, micromatch, standard, nyc, laravel-mix, redux, axios, etc.).
- Successfully ran the data collection for 2 repositories to validate the pipeline, as full execution for all 15 proved time-intensive.
- Saved each repository’s data as structured JSON for later indexing.

### 2. **Review JSON and plan ingestion**

- Analyzed JSON structure to identify key analytic fields (issues, comments, reactions, etc.).
- Designed a **multi-index** Elasticsearch model: separate indices for `repos`, `commits`, `pull_requests`, `issues`, and `contributors`, linked by a shared `repo_name`.
- Enables fast cross-repo filtering, aggregation, and visualization in OpenSearch.

### 3. **Use npm packages Tanner provided**

- Treated Tanner’s npm packages as the target GitHub repositories for data collection, capturing collaboration activity.

## Ingest Data into Elasticsearch

### 1. **Test local ingestion**

- Implemented a multi-index script to flatten JSON and bulk-index data into `github_repos`, `github_commits`, `github_pull_requests`, `github_issues`, and `github_contributors`.
- Verified successful connection and document counts.

### 2. **Compare index structures**

- Tested:
  - Separate indices per entity (chosen approach)
  - One index per repository
  - Single combined index
- Entity-based indexing proved most scalable and query-efficient.

### 3. **Define index mappings**

- Each Elasticsearch index was given entity-specific mappings (`keyword`, `integer`, `text`, `date`) to ensure consistent filtering, search, and aggregation.

### 4. **Explore Compute Canada / Dockerization**

- Deferred to once the local pipeline is finalized and stable.

## Formulate Test Queries

### 1. **Build queries**

- Ran initial queries on commit frequency, issue closure rates, and PR review activity to validate indexed data.

### 2. **Focus on exploratory over production**

- Played around with a few different queries to see what we can pull, pretty consistent with last week.

### 3. **Check indexing effectiveness**

- In process of verifying that the shared `repo_name` field links entities across indices to support cross-repository analytics.

---

# COSC 448 - Tasks (Week 4)

## Action Items

- [x] Compare **GitHub API v3 vs v4** differences in `fetch`
- [x] Test if v4 can replicate a **Perceval fetch** (v3)
- [x] Build test pipeline for v3 and v4: fetch **all data from API** → filter later (focus on **raw data collection**)
- [x] (Deprioritized) Identity deduplication → not implementing for now
- [x] Determine how to store **cleaned data in Elasticsearch**
- [x] Document how data flows into Elasticsearch

## GitHub API Data to Extract

- **Repositories** → creation date, forked or not, org, username, stars, about/description, watchers, releases (date, version, count), contributors, number of files (proxy for differences), reactions, topics
- **Commits** → author, committer, delta (LOC added/removed/changed)
- **Pull Requests** → authors, reviewers, comments, # contributors not reviewers, member roles, creation time, status, changes requested, timestamps, event info, merge comment, GitHub Actions, etc.
- **Issues** → issue → PR linkage, comments, contributors
- **Contributors** → all available contributor metadata

## References & Resources

- **GitHub API v3:** [https://docs.github.com/en/rest](https://docs.github.com/en/rest)
- **GitHub API v4:** [https://docs.github.com/en/graphql](https://docs.github.com/en/graphql)
- **Elasticsearch:** [https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)
- **Perceval:** [https://perceval.readthedocs.io/en/latest/](https://perceval.readthedocs.io/en/latest/)

# COSC 448 - Summary (Week 4)

## 1. Compare GitHub API v3 vs v4 (Fetch Differences)

**REST v3:**

- Fixed structures; often over-fetches.
- Requires multiple calls to gather related data.
- Pagination via **Link headers** (`next`, `last`).
- Example: fetching followers and each of their followers ≈ 1+1 calls.

**GraphQL v4:**

- Returns only requested fields in a custom structure.
- Can combine multiple REST calls into one query.
- Pagination via **cursor-based** approach (`first`, `after`, `pageInfo`).
- Example: same followers query = 1 call.

**Conclusion:**

- v3 = breadth and simplicity.
- v4 = precision and efficiency.

## 2. Can v4 Replicate a Perceval (v3) Fetch?

- **Yes.** v4 can retrieve repositories, commits, pull requests, issues, contributors, and releases.
- **v3/Perceval:** works as a “dump everything” approach; minimal query design but more data than needed.
- **v4:** requires custom queries + cursors; avoids over-fetching but needs more setup.

## 3. Build Pipelines (Fetch All → Filter Later)

**REST v3:**

- Data retrieved in chunks (`/commits`, `/pulls`, `/issues`, `/releases`).
- Pagination handled by Link headers.
- Mirrors Perceval’s raw JSON dumps.
- Straightforward, but slower on large repositories and prone to rate limits.

**GraphQL v4:**

- Requires explicit field and relationship requests.
- Cursor-based pagination.
- Less convenient for bulk collection but fewer bytes transferred and more efficient with rate limits.

**Conclusion:**

- REST is better for “firehose” raw dumps.
- GraphQL is better for focused queries.

## 4. Store Cleaned Data in Elasticsearch (From Tests)

- Raw `v3_repo_data.json` was deeply nested.
- Direct ingestion produced log-like records (`@timestamp`, `field`, `message`).
- **Solution:** flatten into consistent documents with schema-defined fields.
- Created new index: **github-clean**, mapping fields such as:
  - `type`, `author`, `sha`, `date`, `message`, `state`, `title`, `url`
- One document per artifact: repository, commit, issue, pull request, review.

## 5. Document Data Flow into Elasticsearch

1. **Fetch** data via API (v3/v4) → save raw JSON.
2. **Clean & transform** → flatten structures, add `type`, keep key fields.
3. **Index** into Elasticsearch → determine mappings (`keyword`, `text`, `date`, etc.) for efficient search + aggregation.
4. **Query & analyze:**
   - Use **ES|QL** for analysis (approvals per reviewer, messages by author).
   - Use **client.search** for targeted free-text lookups (e.g., commits mentioning _WeatherStation_).

## Summary of Testing

### Data Retrieval

- **`v3_data_retrieval.py`**: repo metadata, topics, file count, releases, commits (metadata-only for speed), PRs (reviews/comments/timeline), issues (comments/reactions), contributors; **Link** pagination → **`v3_repo_data.json`**.
- **`v4_data_retrieval.py`**: two-phase PR harvest (paged metadata → per-PR details) with **cursor** pagination → **`v4_pr_data.json`**.

### Indexing

- **`index_elasticsearch.py`**: created **`github-clean`** with explicit mappings; flattened + bulk-indexed repo/commit/issue/PR/review docs.

### Querying

- **`query_elasticsearch.py`**: ES|QL examples (**messages by author**, **approvals per reviewer**, **commits/day/author**) + classic text search.

## Key Takeaways

- **Flow:** API (v3/v4) → JSON → Clean/Flatten → ES index → ES|QL/search.
- **v3 vs v4:** v3 = simple, chatty raw dumps; v4 = designed, precise.
- **Why ES:** clean mappings unlock analytics GitHub doesn’t surface (reviewer activity, message volume, timelines).
- **Demo:** show both data retrieval code + JSON, and ElasticSearch index/query code with output.

---

# COSC 448 - Tasks (Week 3)

## Action Items

- [x] Investigate whether we can view and analyze the source code in OpenSearch Dashboards using GitHub data through GrimoireLab.
- [x] Develop a clear understanding of how GrimoireLab pulls GitHub and Git data.
- [x] Research how LFx collects its data, compare what they provide versus what Perceval provides, and review their scripts for fetching data.
- [x] Determine whether LFx uses OpenSearch or if they rely on a different solution for data storage and visualization.
- [x] Define exactly what GitHub data we want to collect and specify which data points should be included.
- [x] Verify whether Perceval is up to date with the current GitHub API and the data it provides.
- [x] Analyze the memory and performance differences between collecting all GitHub API data versus collecting only filtered data.
- [x] Propose an initial idea for a pipeline.

## References & Resources

- [[Perceval Documentation](https://perceval.readthedocs.io/en/latest/)](https://perceval.readthedocs.io/en/latest/)
- [[GrimoireLab Tutorial](https://chaoss.github.io/grimoirelab-tutorial/)](https://chaoss.github.io/grimoirelab-tutorial/)
- [[LFx Insights](https://lfx.linuxfoundation.org/tools/insights/)](https://lfx.linuxfoundation.org/tools/insights/)
- [[GitHub API Documentation](https://docs.github.com/en/rest)](https://docs.github.com/en/rest)

# COSC 448 - Summary (Week 3)

## 1. Investigate Viewing and Analyzing Source Code in OpenSearch Dashboards

**Steps:**

- Ran GrimoireLab with a GitHub repo and reviewed the CSV export of the data.

**Findings:**

- **Stored by GrimoireLab (Perceval + GrimoireELK):**
  - Repository metadata (origin, repository, url_id, etc.)
  - Issue details (title, state, created_at, closed_at, labels, milestone, etc.)
  - User info (user_login, user_name, author_name, assignee_name, etc.)
  - Enrichment fields (metadata**gelk_version, metadata**enriched_on, grimoire_creation_date, etc.)
- **Missing:**
  - Only issue/project metadata is stored.
  - No raw source code files; only repo URLs.

**Explanation:**

- Perceval fetches metadata from GitHub.
- GrimoireELK processes Perceval JSON into Elasticsearch/OpenSearch with enrichment fields.
- GitHub API only exposes metadata (issues, PRs, commits), not full code.
- Commits may include diffs as metadata but not full files.
- Repository contents require a custom backend to clone and parse code.

**Conclusion:**

- GrimoireLab supports analyzing activity, issues, PRs, and commit metadata, but not raw source code.
- Analyzing code directly requires:
  - Custom Perceval backend to clone and parse repositories, or
  - Additional pipeline stage to fetch/analyze code using commit SHAs.

## 2. Develop Understanding of How GrimoireLab Pulls GitHub Data

- GrimoireLab uses Perceval to fetch GitHub issues, pull requests, and repository metadata.
- Authentication options:
  - Without credentials – basic access, low rate limits
  - With user token – higher limits and token rotation
- Perceval can run via CLI or Python scripts; Python scripts allow multiple API tokens to bypass rate limits.
- Perceval structures API JSON into a consistent schema.

**Example Output (Test Run):**

- Repository Metadata: origin, repository, uuid, updated_on
- Issue/PR Details: title, body, state, created_at, closed_at, updated_at, labels, milestone, url
- User Info: user_login, user_name (author/assignee)
- Commit/Activity Links: html_url, comments_url, events_url
- Enrichment Fields: backend_name ("GitHub"), metadata**enriched_on, metadata**gelk_version, grimoire_creation_date

**Conclusion:**

- GrimoireLab depends on Perceval’s GitHub backend.
- Output is normalized JSON covering issues, PRs, and repository metadata.

## 3. Research LFx Data Collection and Compare with Perceval

**Steps:**

- LFx Insights evaluates project health: activity, dependencies, contributor base, governance, responsiveness, security.
- LFx pipeline:
  1. Raw Data Collection – GitHub APIs (initial correctness ~20%)
  2. Data Onboarding – identity normalization
  3. AI Enrichment & Deduplication – increases correctness to ~90%
  4. Manual QA & Feedback – human verification, quality >90%

**GitHub Data Collected:**

- Repository activity events, PRs, issues, commits
- Maintainer identification from MAINTAINERS files

**Script Comparison:**

- **LFx:**
  - Python, GraphQL-based, vertical pipeline, heavy enrichment and QA
  - Focus on curated, actionable health metrics
- **Perceval:**
  - Python, REST API-based, horizontal modular backends, minimal enrichment
  - Focus on comprehensive raw JSON collection

**Conclusion:**

- LFx delivers curated health insights; Perceval provides raw events for downstream processing.

## 4. Determine LFx Data Storage and Visualization

- **Storage:** Community Data Platform (CDP) – aggregates, cleans, enriches, and analyzes developer/community data across projects.
- **Features:**
  - Consolidates interactions across platforms
  - Identity resolution and profile enrichment
  - 360° view of contributors/organizations
  - Self-hosting via Kubernetes/Docker
- **Visualization:** Nuxt 3 + Tailwind CSS dashboards, analytics via Tinybird

## 5. Define GitHub Data to Collect

**Comparison Table:**

| Data Category | LFx Insights                                        | Perceval                                        | GitHub API (v3/v4)                                                                                                                                                                                       |
| ------------- | --------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Repositories  | Name, description, visibility, topics, stars, forks | Name, URL, description, creation/update dates   | v3: /repos/{owner}/{repo} → name, description, topics, stargazers_count, forks_count, created_at, updated_at<br>v4: repository {name, description, stargazerCount, forkCount, createdAt, updatedAt}      |
| Commits       | SHA, author, timestamp, message                     | SHA, author, committer, message, timestamp      | v3: /repos/{owner}/{repo}/commits → SHA, author, committer, message, date<br>v4: commitHistory { edges { node { message, committedDate, author { user { login } } } } }                                  |
| Pull Requests | Author, reviewers, timestamps, merge status         | State, labels, creation/closing times, comments | v3: /repos/{owner}/{repo}/pulls → title, author, state, merged_at, reviewers, comments<br>v4: pullRequests { totalCount, nodes { title, state, merged, author { login }, reviews { totalCount } } }      |
| Issues        | Author, assignees, labels, state, timestamps        | State, labels, creation/closing times, comments | v3: /repos/{owner}/{repo}/issues → title, state, labels, assignees, created_at, closed_at<br>v4: issues { totalCount, nodes { title, state, labels { nodes { name } }, assignees { nodes { login } } } } |
| Contributors  | Username, contributions count                       | Username, activity count                        | v3: /repos/{owner}/{repo}/contributors → login, contributions<br>v4: mentionableUsers { totalCount, nodes { login } }                                                                                    |

**REST vs GraphQL:**

- REST (v3): pre-determined structure, multiple requests often needed
- GraphQL (v4): precise queries, single request, efficient, flexible

## 6. Verify Perceval Update Status

- Latest commit: active maintenance
- Issue search: some minor API adjustments required
- Uses REST API v3 only, not GraphQL v4
- Focuses on raw data collection (issues, PRs, commits, comments)
- Minimal enrichment (timestamps, UUIDs, API versioning)

**Conclusion:**

- Perceval is up to date for REST API v3; suitable for raw GitHub data collection.

## 7. Analyze Memory and Performance Differences

**Test Repository:** COSC 310 project  
**Script:** Custom Python using Perceval, JSON output

**Results:**

| Dataset                            | File Size       | Runtime | Current Memory | Peak Memory  |
| ---------------------------------- | --------------- | ------- | -------------- | ------------ |
| All data (issues + PRs + events)   | 9,741,243 bytes | 32.60 s | 8,062.13 KB    | 10,344.44 KB |
| Only issues (filtered client-side) | 2,830,487 bytes | 30.00 s | 5,117.09 KB    | 9,069.02 KB  |

**Observations:**

- Filtering issues reduces file size and memory moderately.
- Runtime improvement minimal; REST API returns issues + PRs together.
- No efficient way to fetch only issues directly via Perceval (I think, may need to look into this further).

## 8. Propose Initial Pipeline Idea

1. **Raw Data Collection:**

   - Perceval pulls GitHub metadata (issues, PRs, commits, comments, milestones)
   - Store raw JSON in OpenSearch or staging database

2. **Enrichment Layer (inspired by LFx/CDP):**

   - Identity resolution across accounts/emails
   - Organization mapping
   - Deduplication of issues, PRs, commits
   - Optional AI enrichment (normalize contributor names, extract roles, infer maintainers)

3. **Implementation Options:**

   - Standalone Python scripts for JSON processing
   - Integrate CDP APIs (if accessible)
   - Custom ETL with Pandas, dicts, or Spark

4. **Visualization & Analysis:**
   - Store cleaned, deduplicated, identity-resolved data in OpenSearch
   - Use OpenSearch Dashboards or Grafana to visualize project activity and contributor metrics

---

# COSC 448 - Tasks (Week 2)

## Action Items

- [x] Get familiar with **Perceval** and **Sorting Hat**.
- [x] Follow the [GrimoireLab tutorial](https://chaoss.github.io/grimoirelab-tutorial/) and install the Docker container to play around with GrimoireLab.
- [x] Investigate whether we can use tools from [LFx Insights](https://lfx.linuxfoundation.org/tools/insights/) to extract data.
- [x] Learn the **GitHub API** and identify data points we can extract.
- [x] Create an **Alliance Canada** account → check the Staser-Lab repo (resources document).

## References & Resources

- **GrimoireLab Tutorial:** [https://chaoss.github.io/grimoirelab-tutorial/](https://chaoss.github.io/grimoirelab-tutorial/)
- **Perceval:** [https://perceval.readthedocs.io/en/latest/](https://perceval.readthedocs.io/en/latest/)
- **SortingHat:** [https://chaoss.github.io/grimoirelab-tutorial/sortinghat](https://chaoss.github.io/grimoirelab-tutorial/sortinghat)
- **Hatstall:** [https://github.com/chaoss/grimoirelab-hatstall](https://github.com/chaoss/grimoirelab-hatstall) _(might be outdated)_
- **GrimoireElk:** [https://pypi.org/project/grimoire-elk/](https://pypi.org/project/grimoire-elk/)

# COSC 448 - Summary (Week 2)

## 1. Get Familiar with Perceval and SortingHat

1. Reviewed the documentation for Perceval and SortingHat. The Perceval documentation was simple and straightforward, while SortingHat/Hatstall was quite confusing and I couldn’t get it running.
2. **Perceval** is a tool in the GrimoireLab ecosystem that collects data from software development and collaboration platforms like GitHub, Jira, and mailing lists. It standardizes this data into a common format, making it easier to analyze and visualize. Essentially, it acts as the first step in the GrimoireLab pipeline, gathering and preparing data for further processing.
3. I tried to set up **SortingHat** on my Mac, working on the Django project and connecting it to MySQL, but ran into problems with missing modules and dependency errors. I struggled with running migrations and getting the frontend to display properly, as Django couldn’t find my static files. Creating an admin user was tricky because the commands required environment variables and a password, which caused additional errors resulting from the problems with the dependencies. I also explored integrating SortingHat with Hatstall and looked at how it collects and analyzes repository data, but never got it fully running. At the same time, I successfully got Perceval working and was able to collect data from Git repositories. I played around with the demos in Perceval’s documentation to see how the data could be structured and analyzed.

## 2. Follow the GrimoireLab Tutorial and Install the Docker Container

1. Successfully installed and ran the GrimoireLab Docker container. See images on my local machine/maybe run a small demo (takes time to get everything running though).
2. Configured `projects.json` and `setup.cfg` to pull data from my project group’s repo from COSC 310, along with the GrimoireLab demo data. I got the GitHub data but couldn’t retrieve the Git data; will investigate further.
3. Setup on Mac and pulling data took a long time due to lack of detailed online documentation.
4. Became somewhat familiar with the GrimoireLab pipeline:
   - **Data collection by Perceval:** Collects raw data from repositories and issue trackers.
   - **Identity management by SortingHat:** Cleans identities to avoid duplicates and mismatches.
   - **Data storage and indexing by Elasticsearch:** Stores data for fast querying and aggregation.
   - **Analysis and dashboards by Kibiter & Sigils:** Helps visualize trends and data using OpenSearch Dashboards.

## 3. Investigate LFx Insights

1. LFx Insights offers information such as:
   - Project’s overall health
   - Who is behind a project
   - Whether a project follows security best practices
   - Tracks adoption and momentum
2. These four metrics could provide valuable insights on specific projects, though feasibility is uncertain. Will investigate further.

## 4. Learn the GitHub API and Identify Extractable Data

1. Reviewed the GitHub REST API documentation.
2. The GitHub API allows extraction of profile information, repository information, or issue information. Repository information includes pull requests, commits, contributors, contents, branches, issues, and statistics found on the repository’s Insights page.
3. See table below for a detailed list of extractable data points.

## 5. List of Data Points Extractable from Repositories Using GitHub API

Drafted a list below:  
| Entity | Endpoint | Key Data Fields | Example Payload (Trimmed) |
|-----------------------|------------------------------------|-------------------------------------------------------------------------------|---------------------------|
| Repository | GET /repos/{owner}/{repo} | id, name, full_name, description, private, fork, archived, default_branch, language, topics[], license.spdx_id, stargazers_count, forks_count, watchers_count, open_issues_count, created_at, updated_at, pushed_at | `json { "id": 123, "name": "my-repo", "full_name": "octocat/my-repo", "language": "Python", "topics": ["analytics","dashboard"], "stargazers_count": 42, "created_at": "2024-01-10T00:00:00Z" }` |
| Commits | GET /repos/{owner}/{repo}/commits | sha, commit.message, commit.author.name, commit.author.date, author.login, stats.additions, stats.deletions, files[].filename, files[].status, files[].patch | `json { "sha": "abc123", "commit": { "message": "Fix bug", "author": {"name": "Alice","date":"2025-09-10"}}, "stats": {"additions":10,"deletions":2}, "files":[{"filename":"main.py","status":"modified"}] }` |
| Pull Requests | GET /repos/{owner}/{repo}/pulls | number, title, state, draft, user.login, assignees[], requested_reviewers[], head.ref, base.ref, created_at, updated_at, merged_at, merge_commit_sha, additions, deletions, changed_files | `json { "number": 42, "title": "Add new feature", "state": "open", "draft": false, "head": {"ref": "feature-branch"}, "base": {"ref": "main"}, "additions": 20, "deletions": 5 }` |
| Issues | GET /repos/{owner}/{repo}/issues | number, title, body, state, user.login, assignees[], labels[], milestone, comments, created_at, updated_at, closed_at, reactions.{+1,-1,laugh,...} | `json { "number": 101, "title": "Bug report", "state": "open", "labels": [{"name":"bug","color":"ff0000"}], "reactions": {"+1": 3, "heart": 1} }` |
| Users | GET /users/{username} | login, id, name, company, location, email, bio, blog, twitter_username, public_repos, public_gists, followers, following, created_at, updated_at | `json { "login": "octocat", "name": "The Octocat", "company": "@GitHub", "followers": 1000 }` |
| Organizations | GET /orgs/{org} | login, name, description, blog, location, email, followers, following, public_repos, plan | `json { "login": "my-org", "name": "My Organization", "public_repos": 42 }` |
| Releases | GET /repos/{owner}/{repo}/releases | tag_name, name, body, draft, prerelease, author.login, created_at, published_at, assets[].name, assets[].size, assets[].download_count | `json { "tag_name": "v1.0.0", "name": "Initial Release", "assets": [{"name":"build.zip","download_count":53}] }` |
| Tags | GET /repos/{owner}/{repo}/tags | name, commit.sha | `json [{"name": "v1.0.0", "commit": {"sha":"abc123"}}]` |
| Workflows | GET /repos/{owner}/{repo}/actions/workflows | id, name, state, created_at, updated_at, path | `json { "id": 123, "name": "CI", "state": "active", "path": ".github/workflows/ci.yml" }` |
| Workflow Runs | GET /repos/{owner}/{repo}/actions/runs | status, conclusion, event, head_branch, head_sha, run_attempt, created_at, updated_at, actor.login | `json { "status":"completed","conclusion":"success","head_branch":"main","actor":{"login":"alice"} }` |
| Traffic | GET /repos/{owner}/{repo}/traffic/views | count, uniques, views[].timestamp | `json { "count": 120, "uniques": 80, "views": [{"timestamp":"2025-09-01T00:00:00Z","count":10}] }` |
| Clones | GET /repos/{owner}/{repo}/traffic/clones | count, uniques, clones[].timestamp | `json { "count": 30, "uniques": 20 }` |
| Contributors | GET /repos/{owner}/{repo}/contributors | login, contributions, avatar_url, html_url | `json [{"login":"bob","contributions":50}]` |
| Security Alerts | GET /repos/{owner}/{repo}/dependabot/alerts | dependency.name, severity, state, dismissed_reason, fixed_at | `json { "dependency": {"name":"lodash"}, "severity":"high", "state":"open" }` |
| Code Scanning Alerts | GET /repos/{owner}/{repo}/code-scanning/alerts | rule.id, rule.description, tool.name, state, severity, instances[] | `json { "rule":{"id":"sql-injection"}, "severity":"critical", "state":"open" }` |

## 6. Create an Alliance Canada Account and Check Staser-Lab Repo

1. Created an account, awaiting confirmation by sponsor.

---

# COSC 448 - Tasks (Week 1)

## Action Items

- [x] Get familiar with concept of project.
- [x] Set up slack and environment.
