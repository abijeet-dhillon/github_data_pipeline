# COSC 448 – GitHub Data Retrieval & Indexing Suite

## Project Objective

This repository houses the end-to-end software analytics platform developed for **COSC 448: Directed Studies – Development and Deployment of a Scalable Data Pipeline for Research** at UBC Okanagan. Guided by the week-by-week deliverables tracked in [docs/weekly_updates.md](docs/weekly_updates.md), the project demonstrates how to:

- Automate the retrieval of rich GitHub repository telemetry (metadata, issues, pull requests, commits, contributors, cross-repo references, git blame).
- Clean, normalize, and cache those datasets in deterministic JSON artifacts under `output/{owner_repo}`.
- Index every artifact into Elasticsearch with explicit mappings so Kibana and downstream notebooks can power contributor metrics, PR-issue linkage analysis, churn tracking, and reviewer insights.
- Maintain research-grade code quality through modular architecture, extensive automated tests, and documentation.

## System Overview

The codebase is divided into two cooperative phases:

1. **Retrieval (data acquisition)** – The modules in `src/retrieval` execute authenticated REST and GraphQL calls, handle pagination, apply incremental refreshes, and enrich artifacts (e.g., linking PRs to issues, detecting cross-repo mentions, computing git blame summaries). Run via `python3 src/retrieval/runner.py`; `pipeline.py`/`run_pipeline.py` remain as backward-compatible shims.
2. **Indexing (data publishing)** – The modules in `src/indexing` define Elasticsearch schemas, manage bulk uploads, and enforce consistent index creation. Run via `python3 src/indexing/runner.py`.

Each phase is independently testable, yet they share conventions such as the `repo_name` join key and deterministic hashing helpers.

## Repository Layout

```
├── docs/                     # Supplementary documentation (setup workflows, outputs, analytics, weekly reports)
├── output/                   # Generated JSON artifacts per repository (git-ignored)
├── run_pipeline.py           # Legacy wrapper (delegates to full pipeline)
├── src/
│   ├── pipeline/             # Orchestrator that runs retrieval then indexing
│   ├── retrieval/            # Data collection, GitHub helpers, orchestration
│   └── indexing/             # Elasticsearch config, schemas, client, orchestration
├── tests/                    # Unit tests for retrieval and indexing modules
├── requirements.txt          # Python dependencies
└── README.md                 # You are here
```

Refer to:

- [docs/pipeline_setup.md](docs/pipeline_setup.md) for running the full retrieval → indexing pipeline.
- [docs/individual_setup.md](docs/individual_setup.md) for operating retrieval or indexing independently and running tests.
- [docs/script_overview.md](docs/script_overview.md) for per-module responsibilities and expected inputs/outputs.
- [docs/pipeline_outputs.md](docs/pipeline_outputs.md) for JSON field explanations.
- [docs/project_analytics.md](docs/project_analytics.md) for performance notes, known issues, and optimization ideas.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the full pipeline (retrieval followed by indexing)
python3 src/pipeline/runner.py

# (Optional) Run retrieval only (edit src/retrieval/config.py for repo list)
python3 src/retrieval/runner.py

# (Optional) Run indexing only (configure src/indexing/config.py)
python3 src/indexing/runner.py
```

## Secrets Configuration

The pipeline and indexing layers load credentials from `local_secrets.json`, which is gitignored. Create it by copying `local_secrets.example.json` and inserting your values:

```json
{
  "github_tokens": ["ghp_token1", "ghp_token2"],
  "elasticsearch": {
    "url": "http://localhost:9200",
    "username": "elastic",
    "password": "changeme",
    "api_key": "",
    "verify_tls": false,
    "index_prefix": "",
    "batch_size": 500
  }
}
```

Set `LOCAL_SECRETS_FILE` if you keep the file elsewhere. The tokens and credentials are injected automatically into `src/retrieval/config.py` and `src/indexing/config.py`, so no source edits are required for sensitive data.

Run the full automated test suite:

```bash
# Unit tests
pytest tests

# Coverage-focused run
pytest tests --cov=src.retrieval --cov=src.indexing --cov-report=term-missing
```

For coverage details, see the commands in [docs/individual_setup.md](docs/individual_setup.md).

## Documentation & Progress Tracking

- **Weekly progress:** [docs/weekly_updates.md](docs/weekly_updates.md)
- **Operational docs:** [docs/pipeline_setup.md](docs/pipeline_setup.md), [docs/individual_setup.md](docs/individual_setup.md), [docs/script_overview.md](docs/script_overview.md), [docs/pipeline_outputs.md](docs/pipeline_outputs.md), [docs/project_analytics.md](docs/project_analytics.md)

These artifacts ensure the project satisfies COSC 448’s emphasis on reproducibility, communication, and iterative improvement while enabling other researchers to extend or repurpose the pipeline.
