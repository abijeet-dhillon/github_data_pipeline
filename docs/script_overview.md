# Script Overview

This reference describes the purpose of each script/module, the data it expects, and the service it provides within the GitHub data retrieval and indexing stack.

## Top-Level Entry Points

| Script/Module                | Purpose                                                    | Expected Inputs                                                                   | Service Provided                                                                            |
| --------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `src/retrieval/runner.py`   | Primary CLI module for the retrieval workflow              | Optional CLI repo arguments; GitHub tokens configured in `src/retrieval/config.py` | Launches the GitHub data retrieval workflow without auxiliary wrappers.                    |
| `run_pipeline.py`           | Legacy wrapper delegating to `src.retrieval.runner.main()` | Same as above; kept for backward compatibility                                   | Allows existing tooling/scripts that invoke `run_pipeline.py` to continue working.         |
| `src/indexing/runner.py`    | CLI module for indexing                                   | CLI args defined in `src/indexing/config.py`                                      | Bootstraps Elasticsearch indexing using the modular package.                               |

## Retrieval Modules (`src/retrieval`)

| Module           | Purpose                                                                                     | Key Functions                                                                                                  | Notes                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `config.py`      | Centralizes constants (GitHub tokens, API URLs, paging limits, repo list)                   | N/A (constants)                                                                                                | Environment variables can override limits such as commit pagination and blame sampling.       |
| `http_client.py` | Handles REST & GraphQL requests with retry logic, token rotation, and pagination            | `request_with_backoff`, `paged_get`, `run_graphql_query`                                                       | Ensures resilient API calls across all collectors.                                            |
| `collectors.py`  | Fetches metadata, issues, PRs, commits, contributors, blame summaries, and maintains caches | `get_repo_meta`, `get_issues`, `get_commits`, `collect_repo_blame`, etc.                                       | Outputs normalized JSON artifacts under `output/{owner_repo}`.                                |
| `linkers.py`     | Derives relationships (PR ↔ issue, commits closing issues, cross-repo mentions)             | `find_prs_with_linked_issues`, `find_issues_closed_by_repo_commits`, `find_cross_project_links_issues_and_prs` | Enriches datasets so analytics can track traceability across GitHub entities.                 |
| `runner.py`      | Orchestrates repository processing and file persistence                                     | `process_repo`, `main`                                                                                         | Invoked directly (`python3 src/retrieval/runner.py`); `pipeline.py` remains as a legacy shim. |

## Indexing Modules (`src/indexing`)

| Module       | Purpose                                                                                     | Key Functions                                                   | Notes                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `config.py`  | Stores Elasticsearch connection settings and resolves CLI arguments into `IndexingSettings` | `resolve_settings`, `parse_args`                                | `HARDLOCK` mimics the historic “hardcoded config” behavior; disable it to use CLI flags. |
| `schema.py`  | Defines Elasticsearch mappings plus ID helpers and file-to-index routing                    | `MAPPINGS`, `FILE_TO_INDEX`, `stable_hash_id`, `id_*` functions | Keeps index schemas synchronized with the retrieval outputs.                             |
| `client.py`  | Wraps the Elasticsearch REST API for index creation and `_bulk` uploads                     | `ESClient.ensure_index`, `ESClient.bulk_index`                  | Handles authorization (username/password or API key) and TLS flags.                      |
| `indexer.py` | Scans `output/{owner_repo}`, normalizes `repo_name`, and streams docs to Elasticsearch      | `scan_and_index`, `iter_json`                                   | Provides per-file logging so operators can trace successes/failures.                     |
| `runner.py`  | Glues configuration, client instantiation, and the scan/index workflow                      | `main`                                                          | Invoked directly (`python3 src/indexing/runner.py`); `index_elasticsearch.py` is a legacy shim. |

## Documentation & Analytics

| File                        | Purpose                                                                     |
| --------------------------- | --------------------------------------------------------------------------- |
| `docs/setup.md`             | Installation, configuration, execution, and testing instructions.           |
| `docs/pipeline_outputs.md`  | Field-by-field explanation of every JSON artifact produced by the retrieval phase. |
| `docs/project_analytics.md` | Improvement opportunities, known bugs, and performance analysis notes.      |
| `docs/weekly_updates.md`    | Running log of course deliverables, action items, and completed milestones. |

Use this overview in tandem with the inline docstrings to quickly locate the module responsible for each part of the workflow.
