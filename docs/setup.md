# Setup & Usage Guide

This document explains how to prepare the environment, configure credentials, execute the pipeline/indexing phases, and run the associated tests. The flow mirrors the expectations outlined in the COSC 448 syllabus and the weekly progress targets.

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

## 3. Configure the Pipeline (Data Retrieval)

Edit `src/pipeline/config.py`:

- Populate `GITHUB_TOKENS` with one or more tokens; the runner automatically rotates and handles rate limits.
- Adjust `REPOS` to list the repositories you want to collect (format `owner/repo`).
- Optional environment overrides exist for commit pagination and lookback windows.

## 4. Run the Pipeline

```bash
python3 run_pipeline.py
```

The script prints progress for each repo and writes JSON artifacts to `output/{owner_repo}`. See [docs/pipeline_outputs.md](pipeline_outputs.md) for details on every file.

## 5. Configure Indexing

1. Edit `src/indexing/config.py` (or pass CLI flags when `HARDLOCK = False`):
   - `HARDCODED_DATA_DIR` – Path to the pipeline output folder (default `./output`).
   - `HARDCODED_ES_URL` / credentials / API key – Elasticsearch connection info (recommend using API key for convenience).
   - `HARDCODED_INDEX_PREFIX` – Optional prefix to namespace indices.
   - `HARDCODED_BATCH_SIZE` – Bulk batch size; lower values help avoid HTTP 413 errors for large `repo_blame` docs.
2. Ensure Elasticsearch is running (e.g., via `./elastic-start-local` or your preferred deployment).

## 6. Run Indexing

```bash
python3 run_indexing.py
```

The runner ensures indices exist (using mappings from `src/indexing/schema.py`) and streams each JSON file under `output/` into Elasticsearch via `ESClient.bulk_index`.

## 7. Testing

The repository splits tests between pipeline and indexing layers. Use the following commands from the project root (after activating the virtual environment):

### Pipeline Tests

```bash
# Unit tests
pytest tests/test_collectors.py tests/test_config.py tests/test_http_client.py \
       tests/test_linkers.py tests/test_runner.py

# Coverage-focused run
pytest tests/test_collectors.py tests/test_config.py tests/test_http_client.py \
       tests/test_linkers.py tests/test_runner.py \
       --cov=src.pipeline --cov-report=term-missing
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
pytest tests --cov=src.pipeline --cov=src.indexing --cov-report=term-missing
```

## 8. Operational Tips

- **GitHub rate limits:** The pipeline prints retries and token rotations; monitor stdout for warning messages.
- **Elasticsearch payloads:** If you encounter HTTP 413 errors while indexing `repo_blame`, reduce `HARDCODED_BATCH_SIZE` or raise `http.max_content_length` server-side (see [docs/project_analytics.md](project_analytics.md)).
- **Kibana validation:** After indexing, create index patterns (e.g., `issues*`, `commits*`, `repo_blame*`) and run exploratory queries to verify fields/mappings.

Following this checklist ensures anyone can reproduce the dataset end-to-end, aligning with the reproducibility and documentation requirements described in the course syllabus.
