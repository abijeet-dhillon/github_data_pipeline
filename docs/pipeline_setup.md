# Full Pipeline Setup (Retrieval + Indexing)

Use this guide when you want to execute the entire workflow end-to-end: first the retrieval phase that downloads GitHub data, then the indexing phase that publishes those artifacts into Elasticsearch. The pipeline runner ensures retrieval completes successfully before indexing begins.

## 1. Prerequisites
- Python 3.10+
- GitHub Personal Access Token(s) with repo-read privileges
- Docker Desktop (or another container runtime)
- Local or remote Elasticsearch 8.x (the instructions below assume the provided `elastic-start-local` helper)

## 2. Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure Secrets & Repositories
1. Copy `local_secrets.example.json` to `local_secrets.json` and provide:
   - The `github_tokens` array used by retrieval.
   - The `elasticsearch` block (URL, username/password or API key, TLS flag, optional index prefix/batch size).
2. Edit `src/retrieval/config.py` to update the `REPOS` list.
3. Optionally tweak `src/indexing/config.py` defaults (e.g., `HARDCODED_DATA_DIR`) if you need to override the target or disable `HARDLOCK`.

## 4. Start Elasticsearch via Docker
From the repository root:
```bash
curl -fsSL https://elastic.co/start-local | sh
```
Follow the prompts (or the output) to capture the generated credentials/API key. Keep the containers running for the duration of the pipeline run.

## 5. Run the Pipeline Runner
Execute:
```bash
python3 src/pipeline/runner.py
```
- Optional CLI arguments (e.g., `python3 src/pipeline/runner.py owner/repo another/repo`) limit retrieval to those repositories; indexing will still process everything under `output/`.
- The runner calls `src.retrieval.runner.main()` first. When it finishes without raising an exception, it immediately invokes `src.indexing.runner.main()`.

## 6. Verify Results
- Inspect `output/{owner_repo}` to confirm fresh JSON artifacts.
- Open Kibana (default http://localhost:5601) and create index patterns for the datasets (`issues*`, `commits*`, `repo_meta*`, etc.).

## 7. Shut Down Elasticsearch
When finished, stop/remove the local containers:
```bash
cd elastic-start-local
docker compose down
```

For troubleshooting or running retrieval/indexing separately, see [docs/individual_setup.md](individual_setup.md).
