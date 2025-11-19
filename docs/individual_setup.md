# Individual Component Setup & Usage Guide

This document explains how to prepare the environment, configure credentials, execute the retrieval or indexing phases independently, and run the associated tests. The flow mirrors the expectations outlined in the COSC 448 syllabus and the weekly progress targets.

## 1. Prerequisites

- Python 3.10+
- GitHub Personal Access Token(s) with `repo` or public read scope
- Elasticsearch 8.x (local container via `elastic-start-local` or remote cluster)
- Optional: `virtualenv`/`venv` tooling for environment isolation

## 2. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Create `local_secrets.json`

1. Copy `local_secrets.example.json` to `local_secrets.json`.
2. Populate:
   - `github_tokens`: Personal Access Tokens used by the retrieval workflow.
   - `elasticsearch`: Shared connection info (URL, username/password or API key, TLS preference, optional index prefix/batch size).
3. Keep this file out of version control (already gitignored). Set `LOCAL_SECRETS_FILE` if you store it elsewhere.

## 4. Configure the Retrieval Workflow

1. Edit `src/retrieval/config.py` when you need to change `REPOS` or tweak environment-based overrides (pagination, blame sampling, etc.).
2. Optional environment overrides exist for commit pagination and lookback windows.

## 5. Run Retrieval

```bash
python3 src/retrieval/runner.py
```

The retrieval script prints progress for each repo and writes JSON artifacts to `output/{owner_repo}`. See [docs/pipeline_outputs.md](pipeline_outputs.md) for details on every file.

## 6. Configure Indexing

1. Verify `local_secrets.json` is filled out (URL, credentials, API key, TLS preference, optional index prefix/batch size). `src/indexing/config.py` ingests these values automatically, and the same secrets file powers the retrieval layer.
2. Adjust `src/indexing/config.py` only if you need different defaults for `HARDCODED_DATA_DIR` or to disable `HARDLOCK` and accept CLI overrides.
3. Ensure Elasticsearch is running (e.g., via `./elastic-start-local` or your preferred deployment).

## 7. Run Indexing

```bash
python3 src/indexing/runner.py
```

The runner ensures indices exist (using mappings from `src/indexing/schema.py`) and streams each JSON file under `output/` into Elasticsearch via `ESClient.bulk_index`.

## 8. Testing

The repository splits tests between retrieval and indexing layers. Use the following commands from the project root (after activating the virtual environment):

### Retrieval Tests

```bash
# Unit tests
pytest tests/test_collectors.py tests/test_config.py tests/test_http_client.py \
       tests/test_linkers.py tests/test_runner.py

# Coverage-focused run
pytest tests/test_collectors.py tests/test_config.py tests/test_http_client.py \
       tests/test_linkers.py tests/test_runner.py \
       --cov=src.retrieval --cov-report=term-missing
```

### Indexing Tests

```bash
# Unit tests
pytest tests/test_es_client.py tests/test_index_schema.py tests/test_indexer.py \
       tests/test_indexing_config.py tests/test_indexing_runner.py

# Coverage-focused run
pytest tests/test_es_client.py tests/test_index_schema.py tests/test_indexer.py \
       tests/test_indexing_config.py tests/test_indexing_runner.py \
       --cov=src.indexing --cov-report=term-missing
```

### Full Suite

```bash
pytest tests            # quick regression check
pytest tests --cov=src.retrieval --cov=src.indexing --cov-report=term-missing
```

## 9. Operational Tips

- **GitHub rate limits:** The retrieval layer prints retries and token rotations; monitor stdout for warning messages.
- **Elasticsearch payloads:** If you encounter HTTP 413 errors while indexing `repo_blame`, reduce `HARDCODED_BATCH_SIZE` or raise `http.max_content_length` server-side (see [docs/project_analytics.md](project_analytics.md)).
- **Kibana validation:** After indexing, create index patterns (e.g., `issues*`, `commits*`, `repo_blame*`) and run exploratory queries to verify fields/mappings.

Following this checklist ensures anyone can reproduce the dataset end-to-end, aligning with the reproducibility and documentation requirements described in the course syllabus.
