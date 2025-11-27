# Project Analytics & Operational Insights

This report summarizes observed performance characteristics, opportunities for optimization, and known issues discovered while developing the COSC 448 GitHub data retrieval and indexing suite.

## Areas of Improvement / Optimization

1. **Adaptive Bulk Sizes** – The current `HARDCODED_BATCH_SIZE` applies to every JSON file. Introducing file-aware batch sizing (e.g., smaller batches for `repo_blame`, larger ones for lightweight datasets) would reduce run times without triggering 413 errors.
2. **Parallel Repository Processing** – `src.retrieval.runner.process_repo()` runs serially. A worker pool (with safeguards for GitHub rate limits) could shorten end-to-end extraction when targeting many repositories.
3. **Incremental Indexing** – Today indexing rewrites entire indices. Tracking `_id` hashes and using partial updates would reduce bulk payloads for reruns.
4. **Observability Hooks** – Streaming metrics (requests per minute, retry counts, index latency) to Prometheus or StatsD would make regressions visible sooner and satisfy future research instrumentation goals.
5. **GraphQL-centric Retrieval** – Migrating more endpoints to GitHub’s v4 GraphQL API could cut runtime, but the v3 REST API still exposes the richest data for bulk dumps. Any migration would need careful auditing to avoid losing fields.

## Known Bugs / Risks

- **Large `repo_blame` uploads (HTTP 413):** Elasticsearch rejects oversized `_bulk` payloads when many blame documents are sent together (observed on `rollup/rollup`). Mitigate by lowering `HARDCODED_BATCH_SIZE` or raising `http.max_content_length` server-side.
- **GitHub token exhaustion:** When every Personal Access Token is rate limited, the retrieval layer sleeps for `RATE_LIMIT_TOKEN_RESET_WAIT_SEC`. Operators should provide multiple fresh tokens to avoid hour-long idle periods.
- **Missing merge commits during PR linkage (HTTP 422):** When scanning PRs for issue-closing keywords in merge messages, some repositories return “No commit found for SHA” for the reported `merge_commit_sha`. This happens when PRs were squashed/rebased or the merge object was later GC’d on GitHub’s side. We log the 422 and skip the merge-message scan; downstream data still populates, but linkage from that specific merge commit cannot be derived.
- **Cross-repo parsing sometimes yields 404s:** Some references resolve to GitHub URLs that return 404 (e.g., file anchors formatted like issues, deleted repos/issues, or stale links). GitHub answers “Not Found” for those resources; we log the warning and keep the source entry with a null target. No clean suppression exists yet without risking missed legitimate cross-repo links.

## Performance Analysis

- **Extraction Throughput:** Large repositories can take well over thirty minutes to process end-to-end because commit pagination, blame lookups, and enrichment requests scale with repository history. Incremental runs that leverage cached JSON finish significantly faster because only delta issues/commits are requested.
- **Indexing Latency:** Most datasets ingest at ~5–7k docs/sec with Elasticsearch running locally via `elastic-start-local`. `repo_blame` is the outlier (bulk uploads often approach the default 100MB content limit); tuning batch sizes or pre-chunking files keeps indexing in a stable 1–2k docs/sec range.
- **Test Suite Duration:** `pytest tests` completes in ~0.1s on a modern laptop because collectors and indexers rely on mocks. This encourages frequent regression testing after each code change.

Revisit this document as the project evolves—logging new risks and documenting mitigations ensures the retrieval workflow remains reliable for future COSC 448 cohorts and researchers.
