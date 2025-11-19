# COSC 448 – GitHub Data Pipeline & Indexing Suite

## Project Objective

This repository houses the end-to-end software analytics platform developed for **COSC 448: Directed Studies – Development and Deployment of a Scalable Data Pipeline for Research** at UBC Okanagan. Guided by the outcomes published in the [course syllabus](docs/cosc448-syllabus.pdf) and the week-by-week deliverables tracked in [docs/weekly_updates.md](docs/weekly_updates.md), the project demonstrates how to:

- Automate the retrieval of rich GitHub repository telemetry (metadata, issues, pull requests, commits, contributors, cross-repo references, git blame).
- Clean, normalize, and cache those datasets in deterministic JSON artifacts under `output/{owner_repo}`.
- Index every artifact into Elasticsearch with explicit mappings so Kibana and downstream notebooks can power contributor metrics, PR-issue linkage analysis, churn tracking, and reviewer insights.
- Maintain research-grade code quality through modular architecture, extensive automated tests, and documentation.

## System Overview

The codebase is divided into two cooperative phases:

1. **Pipeline (data acquisition)** – The modules in `src/pipeline` execute authenticated REST and GraphQL calls, handle pagination, apply incremental refreshes, and enrich artifacts (e.g., linking PRs to issues, detecting cross-repo mentions, computing git blame summaries). The compatibility wrapper `run_pipeline.py` simply invokes `src.pipeline.runner.main()`.
2. **Indexing (data publishing)** – The modules in `src/indexing` define Elasticsearch schemas, manage bulk uploads, and enforce consistent index creation. The compatibility wrapper `run_indexing.py` simply invokes `src.indexing.runner.main()`.

Each phase is independently testable, yet they share conventions such as the `repo_name` join key and deterministic hashing helpers.

## Repository Layout

```
├── docs/                     # Supplementary documentation (setup, outputs, analytics, syllabus, weekly reports)
├── output/                   # Generated JSON artifacts per repository (git-ignored)
├── run_pipeline.py           # Wrapper that calls src.pipeline.runner.main()
├── run_indexing.py           # Wrapper that calls src.indexing.runner.main()
├── src/
│   ├── pipeline/             # Data collection, GitHub helpers, orchestration
│   └── indexing/             # Elasticsearch config, schemas, client, orchestration
├── tests/                    # Unit tests for pipeline and indexing modules
├── requirements.txt          # Python dependencies
└── README.md                 # You are here
```

Refer to:

- [docs/setup.md](docs/setup.md) for environment preparation, execution steps, and test commands.
- [docs/script_overview.md](docs/script_overview.md) for per-module responsibilities and expected inputs/outputs.
- [docs/pipeline_outputs.md](docs/pipeline_outputs.md) for JSON field explanations.
- [docs/project_analytics.md](docs/project_analytics.md) for performance notes, known issues, and optimization ideas.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the GitHub data pipeline (edit src/pipeline/config.py for repo list)
python3 run_pipeline.py

# Index JSON artifacts into Elasticsearch (configure src/indexing/config.py)
python3 run_indexing.py
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

Set `LOCAL_SECRETS_FILE` if you keep the file elsewhere. The tokens and credentials are injected automatically into `src/pipeline/config.py` and `src/indexing/config.py`, so no source edits are required for sensitive data.

Run the full automated test suite:

```bash
pytest tests
```

For coverage details, see the commands in [docs/setup.md](docs/setup.md).

## Documentation & Progress Tracking

- **Syllabus reference:** [docs/cosc448-syllabus.pdf](docs/cosc448-syllabus.pdf)
- **Weekly progress:** [docs/weekly_updates.md](docs/weekly_updates.md)
- **Operational docs:** [docs/setup.md](docs/setup.md), [docs/script_overview.md](docs/script_overview.md), [docs/pipeline_outputs.md](docs/pipeline_outputs.md), [docs/project_analytics.md](docs/project_analytics.md)

These artifacts ensure the project satisfies COSC 448’s emphasis on reproducibility, communication, and iterative improvement while enabling other researchers to extend or repurpose the pipeline.
