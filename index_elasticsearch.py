from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import time
import argparse
import hashlib
import requests
import argparse


HARDLOCK = True  # if True, force the hardcoded values below
HARDCODED_DATA_DIR = "./output"                
HARDCODED_ES_URL = "http://localhost:9200"     
HARDCODED_ES_USERNAME = None               
HARDCODED_ES_PASSWORD = None             
HARDCODED_ES_API_KEY  = "" # ONLY PUT IN API KEY
HARDCODED_VERIFY_TLS  = False                   


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index initial_pipeline.py outputs into Elasticsearch (hardcoded config)."
    )
    parser.add_argument("--data-dir", default=HARDCODED_DATA_DIR,
                        help="Root folder produced by initial_pipeline.py (hardcoded by default)")
    parser.add_argument("--es-url", default=HARDCODED_ES_URL,
                        help="Elasticsearch base URL (hardcoded by default)")
    parser.add_argument("--username", default=HARDCODED_ES_USERNAME,
                        help="Basic auth username (hardcoded by default)")
    parser.add_argument("--password", default=HARDCODED_ES_PASSWORD,
                        help="Basic auth password (hardcoded by default)")
    parser.add_argument("--api-key", default=HARDCODED_ES_API_KEY,
                        help="ApiKey value (base64 id:key) (hardcoded by default)")

    parser.add_argument("--verify-tls", type=lambda x: str(x).lower() in {"1","true","yes","y","on"},
                        default=HARDCODED_VERIFY_TLS,
                        help="Verify TLS certificates (default hardcoded)")
    parser.add_argument("--prefix", default="",
                        help="Optional index name prefix (e.g., 'cosc448_')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse but do not send anything to Elasticsearch")
    parser.add_argument("--batch-size", type=int, default=1000,
                        help="Docs per bulk request (default: 1000)")

    return parser.parse_args()


class ESClient:
    def __init__(self, base_url: str, username: Optional[str], password: Optional[str],
                 api_key: Optional[str], verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.verify = bool(verify_tls)

        if api_key:
            self.session.headers["Authorization"] = f"ApiKey {api_key}"
        elif username and password:
            self.session.auth = (username, password)


    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{path}"


    def ensure_index(self, name: str) -> None:
        r = self.session.head(self._url(name), verify=self.verify)
        if r.status_code == 404:
            body = {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {"dynamic": True}
            }
            cr = self.session.put(self._url(name), data=json.dumps(body), verify=self.verify)
            if cr.status_code >= 300:
                raise RuntimeError(f"Failed to create index '{name}': {cr.status_code} {cr.text}")


    def bulk_index(self, index: str, docs: Iterable[Dict[str, Any]], id_func=None, batch_size: int = 1000) -> Tuple[int, int]:
        ok_total = 0
        fail_total = 0
        actions: List[str] = []
        count = 0

        def flush():
            nonlocal ok_total, fail_total, actions, count
            if not actions:
                return
            payload = "\n".join(actions) + "\n"
            actions = []
            count = 0
            r = self.session.post(self._url("_bulk"),
                                  data=payload,
                                  headers={"Content-Type": "application/x-ndjson"},
                                  verify=self.verify)
            if r.status_code >= 300:
                print(f"  ❌ Bulk HTTP {r.status_code}: {r.text[:500]}")
                fail_total += payload.count("\n") // 2 
                return

            resp = r.json()
            if resp.get("errors"):
                for item in resp.get("items", []):
                    meta = item.get("index") or item.get("create") or {}
                    status = meta.get("status", 500)
                    if 200 <= status < 300:
                        ok_total += 1
                    else:
                        fail_total += 1
                first_err = next((it for it in resp.get("items", []) if (it.get("index") or {}).get("error")), None)
                if first_err:
                    print(f"  ⚠️  First item error: {first_err}")
            else:
                ok_total += len(resp.get("items", []))

        for doc in docs:
            _id = id_func(doc) if id_func else None
            meta = {"index": {"_index": index}}
            if _id:
                meta["index"]["_id"] = _id
            actions.append(json.dumps(meta, separators=(",", ":")))
            actions.append(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
            count += 1

            if count >= batch_size:
                flush()

        flush()
        return ok_total, fail_total


def stable_hash_id(doc: Dict[str, Any], salt: str = "") -> str:
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    h = hashlib.sha1((salt + raw).encode("utf-8")).hexdigest()
    return h


def folder_repo_name(repo_dir: Path) -> str:
    name = repo_dir.name
    if "_" in name:
        owner, repo = name.split("_", 1)
        return f"{owner}/{repo}"
    return name.replace("__", "/") 


def ensure_top_repo_name(doc: Dict[str, Any], repo_name: str) -> None:
    if "repo_name" not in doc or not doc["repo_name"]:
        doc["repo_name"] = repo_name


def iter_json(path: Path) -> Iterable[Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        for d in data:
            yield d
    elif isinstance(data, dict):
        yield data
    else:
        yield {"raw": data}


def id_commits(doc: Dict[str, Any]) -> Optional[str]:
    return doc.get("sha") or stable_hash_id(doc, "commit:")


def id_pull_requests(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    num = doc.get("number")
    if rn and num is not None:
        return f"{rn}#pr#{num}"
    return stable_hash_id(doc, "pr:")


def id_issues(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    num = doc.get("number")
    if rn and num is not None:
        return f"{rn}#issue#{num}"
    return stable_hash_id(doc, "issue:")


def id_prs_with_linked_issues(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    num = doc.get("pr_number") or doc.get("number")
    if rn and num is not None:
        return f"{rn}#prlinks#{num}"
    return stable_hash_id(doc, "prlinks:")


def id_issues_closed_by_commits(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    issue_num = doc.get("issue_number") or doc.get("number")
    sha = doc.get("commit_sha") or doc.get("sha")
    if rn and issue_num is not None and sha:
        return f"{rn}#closed#{issue_num}#{sha}"
    return stable_hash_id(doc, "closed:")


def id_repo_meta(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    return rn or stable_hash_id(doc, "repo_meta:")


def id_cross_repo_links(doc: Dict[str, Any]) -> Optional[str]:
    return stable_hash_id(doc, "xrepo:")


FILE_TO_INDEX = {
    "commits.json": ("commits", id_commits),
    "cross_repo_links.json": ("cross_repo_links", id_cross_repo_links),
    "issues_closed_by_commits.json": ("issues_closed_by_commits", id_issues_closed_by_commits),
    "issues.json": ("issues", id_issues),
    "prs_with_linked_issues.json": ("prs_with_linked_issues", id_prs_with_linked_issues),
    "pull_requests.json": ("pull_requests", id_pull_requests),
    "repo_meta.json": ("repo_meta", id_repo_meta),
}


def scan_and_index(es: ESClient, data_dir: Path, index_prefix: str,
                   dry_run: bool = False, batch_size: int = 1000) -> None:
    if not data_dir.exists():
        print(f"Data dir not found: {data_dir}")
        return

    for _, (idx, _) in FILE_TO_INDEX.items():
        name = f"{index_prefix}{idx}"
        if not dry_run:
            es.ensure_index(name)
    print("✅ Ensured indices:",
          ", ".join(f"{index_prefix}{idx}" for idx, _ in FILE_TO_INDEX.values()))

    repo_dirs = [p for p in data_dir.iterdir() if p.is_dir()]
    if not repo_dirs:
        print(f"No per-repo folders found in {data_dir}. Expected subfolders like owner_repo/")
        return

    total_ok = 0
    total_fail = 0
    started = time.time()

    for repo_dir in sorted(repo_dirs):
        repo_name = folder_repo_name(repo_dir)
        print(f"\n=== {repo_name} ===")

        for filename, (idx_base, id_fn) in FILE_TO_INDEX.items():
            path = repo_dir / filename
            if not path.exists():
                continue

            index_name = f"{index_prefix}{idx_base}"
            print(f"  -> {filename} → {index_name}")

            def docs():
                for doc in iter_json(path):
                    ensure_top_repo_name(doc, repo_name)
                    yield doc

            if dry_run:
                _ = sum(1 for _ in docs())
                print(f"     (dry-run) OK parsed")
            else:
                ok, fail = es.bulk_index(index=index_name, docs=docs(), id_func=id_fn, batch_size=batch_size)
                print(f"     indexed: ok={ok} fail={fail}")
                total_ok += ok
                total_fail += fail

    dur = time.time() - started
    print(f"\nDone. Total ok={total_ok}, fail={total_fail}, took {dur:.1f}s")


def main() -> None:
    args = get_args()

    if HARDLOCK:
        args.data_dir = HARDCODED_DATA_DIR
        args.es_url = HARDCODED_ES_URL
        args.username = HARDCODED_ES_USERNAME
        args.password = HARDCODED_ES_PASSWORD
        args.api_key = HARDCODED_ES_API_KEY
        args.verify_tls = HARDCODED_VERIFY_TLS

    data_dir = Path(args.data_dir)
    es = ESClient(
        base_url=args.es_url,
        username=args.username,
        password=args.password,
        api_key=args.api_key,
        verify_tls=args.verify_tls,
    )

    scan_and_index(
        es,
        data_dir=data_dir,
        index_prefix=args.prefix,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()