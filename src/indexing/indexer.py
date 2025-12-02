"""Scanning helpers that stream exported data into Elasticsearch indices."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

try:
    import ijson  # type: ignore
except ImportError:  # pragma: no cover
    ijson = None

from .client import ESClient
from .schema import FILE_TO_INDEX, MAPPINGS

# repo_blame payloads can be extremely large. Keep bulk requests small to avoid 413s.
REPO_BLAME_BATCH_SIZE = 50


def folder_repo_name(repo_dir: Path) -> str:
    """Convert an owner_repo folder name to owner/repo for indexing."""

    name = repo_dir.name
    if "_" in name:
        owner, repo = name.split("_", 1)
        return f"{owner}/{repo}"
    return name.replace("__", "/")


def ensure_repo_name_field(doc: Dict[str, Any], repo_name: str) -> None:
    """Guarantee a top-level repo_name field for consistent filtering."""

    if not doc.get("repo_name"):
        doc["repo_name"] = repo_name


def iter_json(path: Path) -> Iterable[Any]:
    """Yield JSON items from files that may contain a list or a single object."""

    with path.open("rb") as handle:
        first_char = None
        while True:
            ch = handle.read(1)
            if not ch:
                break
            decoded = ch.decode("utf-8")
            if not decoded.isspace():
                first_char = decoded
                break
        handle.seek(0)
        if first_char == "[" and ijson is not None:
            for item in ijson.items(handle, "item"):
                yield item
            return
        data = json.load(handle)
    if isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        yield data
    else:
        yield {"raw": data}


def _extract_repo_blame_metadata(path: Path, repo_name: str) -> Dict[str, Any]:
    """Return top-level metadata without loading the full blame payload."""

    meta_keys = {"repo_name", "ref", "generated_at", "head_commit_sha", "error"}
    meta: Dict[str, Any] = {"repo_name": repo_name}

    if ijson is None:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        for key in meta_keys:
            if key in data:
                meta[key] = data[key]
        return meta

    with path.open("rb") as handle:
        for prefix, event, value in ijson.parse(handle):
            if prefix in meta_keys and event in {"string", "number", "boolean", "null"}:
                meta[prefix] = value
    return meta


def iter_repo_blame_docs(path: Path, repo_name: str) -> Iterable[Dict[str, Any]]:
    """Stream repo_blame entries one file at a time to keep bulk payloads small."""

    meta = _extract_repo_blame_metadata(path, repo_name)

    def _build_doc(file_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        doc = dict(meta)
        doc["files"] = [file_entry] if file_entry is not None else []
        ensure_repo_name_field(doc, repo_name)
        return doc

    count = 0
    if ijson is None:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        for file_entry in data.get("files") or []:
            yield _build_doc(file_entry)
            count += 1
    else:
        with path.open("rb") as handle:
            for file_entry in ijson.items(handle, "files.item"):
                yield _build_doc(file_entry)
                count += 1

    if count == 0:
        yield _build_doc(None)


def scan_and_index(
    es: ESClient,
    data_dir: Path,
    index_prefix: str,
    dry_run: bool = False,
    batch_size: int = 1000,
) -> None:
    """Iterate over repo folders and stream JSON docs into their target indices."""

    if not data_dir.exists():
        print(f"Data dir not found: {data_dir}")
        return

    for _, (idx_name, _) in FILE_TO_INDEX.items():
        full = f"{index_prefix}{idx_name}"
        es.ensure_index(full, MAPPINGS.get(idx_name))
    print("Ensured indices:", ", ".join(f"{index_prefix}{name}" for name, _ in FILE_TO_INDEX.values()))

    repo_dirs = [path for path in data_dir.iterdir() if path.is_dir()]
    if not repo_dirs:
        print(f"No repo subfolders found in {data_dir}. Expected ./output/owner_repo/.")
        return

    total_ok = 0
    total_fail = 0
    started = time.time()

    for repo_dir in sorted(repo_dirs):
        repo_name = folder_repo_name(repo_dir)
        print(f"\n=== {repo_name} ===")

        for filename, (index_name, id_fn) in FILE_TO_INDEX.items():
            file_path = repo_dir / filename
            target_index = f"{index_prefix}{index_name}"

            if not file_path.exists():
                continue

            print(f"  -> {filename} -> {target_index}")

            def gen_docs() -> Iterable[Dict[str, Any]]:
                for doc in iter_json(file_path):
                    ensure_repo_name_field(doc, repo_name)
                    yield doc

            if dry_run:
                count = sum(1 for _ in gen_docs())
                print(f"     (dry-run) parsed {count} docs")
            else:
                effective_batch = REPO_BLAME_BATCH_SIZE if filename == "repo_blame.json" else batch_size
                ok, fail = es.bulk_index(
                    index=target_index,
                    docs=iter_repo_blame_docs(file_path, repo_name)
                    if filename == "repo_blame.json"
                    else gen_docs(),
                    id_func=id_fn,
                    batch_size=effective_batch,
                )
                print(f"     indexed: ok={ok} fail={fail}")
                total_ok += ok
                total_fail += fail

    duration = time.time() - started
    print(f"\nDone. Total ok={total_ok}, fail={total_fail}, took {duration:.1f}s")


__all__ = [
    "folder_repo_name",
    "ensure_repo_name_field",
    "iter_json",
    "iter_repo_blame_docs",
    "scan_and_index",
]
