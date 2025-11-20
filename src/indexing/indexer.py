"""Scanning helpers that stream exported data into Elasticsearch indices."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable

try:
    import ijson  # type: ignore
except ImportError:  # pragma: no cover
    ijson = None

from .client import ESClient
from .schema import FILE_TO_INDEX, MAPPINGS

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
                ok, fail = es.bulk_index(
                    index=target_index,
                    docs=gen_docs(),
                    id_func=id_fn,
                    batch_size=batch_size,
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
    "scan_and_index",
]
