#!/usr/bin/env python3
"""
index_elasticsearch_with_full_mappings.py
-----------------------------------------
Indexes every JSON artifact produced by `rest_pipeline.py` (REST + GraphQL data)
into Elasticsearch, creating indices with explicit, queryable mappings (dynamic: true).

Datasets (per repo folder under ./output/{owner_repo}/):
  - repo_meta.json                -> index: repo_meta
  - issues.json                   -> index: issues
  - pull_requests.json            -> index: pull_requests
  - commits.json                  -> index: commits
  - contributors.json             -> index: contributors
  - prs_with_linked_issues.json   -> index: prs_with_linked_issues
  - issues_closed_by_commits.json -> index: issues_closed_by_commits
  - cross_repo_links.json         -> index: cross_repo_links
  - repo_blame.json               -> index: repo_blame

Each mapping includes `repo_name` for consistent filtering and nested schemas where needed
(e.g., blame ranges, PR links). Hardcoded configuration is retained (HARDLOCK=True) so the
default CLI invocation mirrors local development settings.

Usage:
    1. Set your Elasticsearch credentials and URL in the hardcoded section at the top
       (or override via CLI flags if HARDLOCK is disabled).
    2. Ensure the data directory (default: `./output/`) contains the exported JSON files.
    3. Run:
           python3 index_elasticsearch.py
    4. Optionally add flags:
           --dry-run          # parse but do not upload
           --prefix cosc448_  # add prefix to index names
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import time
import argparse
import hashlib
import requests


# hardcoded config
HARDLOCK               = True  # if True, force the hardcoded values below
HARDCODED_DATA_DIR     = "./output"
HARDCODED_ES_URL       = "http://localhost:9200"
HARDCODED_ES_USERNAME  = None              
HARDCODED_ES_PASSWORD  = None               
HARDCODED_ES_API_KEY   = ""                
HARDCODED_VERIFY_TLS   = False             
HARDCODED_INDEX_PREFIX = ""             
HARDCODED_BATCH_SIZE   = 1000


# CLI
def get_args() -> argparse.Namespace:
    """Parse CLI arguments (overridden by HARDLOCK when enabled)."""
    p = argparse.ArgumentParser(description="Index rest_pipeline.py outputs into Elasticsearch with full, queryable object mappings.")
    p.add_argument("--data-dir", default=HARDCODED_DATA_DIR)
    p.add_argument("--es-url", default=HARDCODED_ES_URL)
    p.add_argument("--username", default=HARDCODED_ES_USERNAME)
    p.add_argument("--password", default=HARDCODED_ES_PASSWORD)
    p.add_argument("--api-key",  default=HARDCODED_ES_API_KEY)
    p.add_argument("--verify-tls", action="store_true", default=HARDCODED_VERIFY_TLS)
    p.add_argument("--prefix", default=HARDCODED_INDEX_PREFIX, help="Index name prefix, e.g., 'gh_'")
    p.add_argument("--batch-size", type=int, default=HARDCODED_BATCH_SIZE)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


# helpers
def stable_hash_id(doc: Dict[str, Any], salt: str = "") -> str:
    """Return a deterministic SHA1 hash for a document (optionally salted)."""
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1((salt + raw).encode("utf-8")).hexdigest()


def folder_repo_name(repo_dir: Path) -> str:
    """
    Convert 'owner_repo' to 'owner/repo'. If folder already encoded differently,
    we do a best-effort normalization.
    """
    name = repo_dir.name
    if "_" in name:
        owner, repo = name.split("_", 1)
        return f"{owner}/{repo}"
    return name.replace("__", "/")


def ensure_repo_name_field(doc: Dict[str, Any], repo_name: str) -> None:
    """
    Guarantee a top-level 'repo_name' field for consistent querying.
    """
    if not doc.get("repo_name"):
        doc["repo_name"] = repo_name


def iter_json(path: Path) -> Iterable[Any]:
    """
    Yield JSON items from a file that may contain either a list or a single object.
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        yield data
    else:
        yield {"raw": data}


# es client
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

    def head_index(self, name: str) -> int:
        r = self.session.head(self._url(name), verify=self.verify)
        return r.status_code

    def create_index_with_mapping(self, name: str, body: Dict[str, Any]) -> None:
        cr = self.session.put(self._url(name), data=json.dumps(body), verify=self.verify)
        if cr.status_code >= 300:
            raise RuntimeError(f"Failed to create index '{name}': {cr.status_code} {cr.text}")

    def ensure_index(self, name: str, mapping: Optional[Dict[str, Any]]) -> None:
        if self.head_index(name) == 404:
            if mapping is None:
                mapping = {"settings": {"number_of_shards": 1, "number_of_replicas": 0},
                           "mappings": {"dynamic": True}}
            self.create_index_with_mapping(name, mapping)

    def bulk_index(self, index: str, docs: Iterable[Dict[str, Any]],
                   id_func=None, batch_size: int = 1000) -> Tuple[int, int]:
        ok_total = 0
        fail_total = 0
        lines: List[str] = []
        def flush() -> Tuple[int, int]:
            nonlocal ok_total, fail_total, lines
            if not lines:
                return (0, 0)
            payload = "\n".join(lines) + "\n"
            resp = self.session.post(self._url(f"{index}/_bulk"), data=payload,
                                     headers={"Content-Type": "application/x-ndjson"},
                                     verify=self.verify)
            lines.clear()
            if resp.status_code >= 300:
                print(f"[error] bulk: {resp.status_code} {resp.text[:500]}")
                return (0, batch_size)
            out = resp.json()
            errs = [it for it in out.get("items", []) if any(v.get("error") for v in it.values())]
            ok = len(out.get("items", [])) - len(errs)
            fail = len(errs)
            ok_total += ok
            fail_total += fail
            return (ok, fail)

        count = 0
        for doc in docs:
            _id = id_func(doc) if id_func else None
            meta = {"index": {"_index": index}}
            if _id:
                meta["index"]["_id"] = _id
            lines.append(json.dumps(meta, separators=(",", ":")))
            lines.append(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
            count += 1
            if count % batch_size == 0:
                flush()
        flush()
        return (ok_total, fail_total)


# index mappings (explicit + dynamic true)

COMMON_SETTINGS = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "text_en": {
                    "type": "standard",
                    "stopwords": "_english_"
                }
            }
        }
    }
}

MAPPINGS: Dict[str, Dict[str, Any]] = {
    "repo_meta": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "id": {"type": "long"},
                "node_id": {"type": "keyword"},
                "name": {"type": "keyword"},
                "full_name": {"type": "keyword"},
                "private": {"type": "boolean"},
                "owner": {"type": "object"},  # owner.login, owner.id, ...
                "html_url": {"type": "keyword"},
                "description": {"type": "text", "analyzer": "text_en"},
                "fork": {"type": "boolean"},
                "url": {"type": "keyword"},
                "homepage": {"type": "keyword"},
                "language": {"type": "keyword"},
                "topics": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "pushed_at": {"type": "date"},
                "stargazers_count": {"type": "integer"},
                "watchers_count": {"type": "integer"},
                "forks_count": {"type": "integer"},
                "open_issues_count": {"type": "integer"},
                "size": {"type": "integer"},
                "license": {"type": "object"},
                "permissions": {"type": "object"},
                "organization": {"type": "object"},
                "default_branch": {"type": "keyword"},
            }
        },
    },

    "issues": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "id": {"type": "long"},
                "node_id": {"type": "keyword"},
                "number": {"type": "integer"},
                "state": {"type": "keyword"},
                "title": {"type": "text", "analyzer": "text_en"},
                "body": {"type": "text", "analyzer": "text_en"},
                "user": {"type": "object"},
                "labels": {"type": "object"},
                "assignee": {"type": "object"},
                "assignees": {"type": "object"},
                "milestone": {"type": "object"},
                "comments": {"type": "integer"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "closed_at": {"type": "date"},
                "author_association": {"type": "keyword"},
                "reactions": {"type": "object"},
                "state_reason": {"type": "keyword"},
                "sub_issues_summary": {"type": "object"},
                "issue_dependencies_summary": {"type": "object"},
                "active_lock_reason": {"type": "keyword"},
            }
        },
    },

    "pull_requests": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "id": {"type": "long"},
                "node_id": {"type": "keyword"},
                "number": {"type": "integer"},
                "state": {"type": "keyword"},
                "locked": {"type": "boolean"},
                "title": {"type": "text", "analyzer": "text_en"},
                "body": {"type": "text", "analyzer": "text_en"},
                "user": {"type": "object"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "closed_at": {"type": "date"},
                "merged_at": {"type": "date"},
                "merge_commit_sha": {"type": "keyword"},
                "assignee": {"type": "object"},
                "assignees": {"type": "object"},
                "requested_reviewers": {"type": "object"},
                "requested_teams": {"type": "object"},
                "labels": {"type": "object"},
                "milestone": {"type": "object"},
                "draft": {"type": "boolean"},
                "head": {"type": "object"},  # includes head.user, head.repo (objects)
                "base": {"type": "object"},  # includes base.user, base.repo (objects)
                "_links": {"type": "object"},
                "author_association": {"type": "keyword"},
                "auto_merge": {"type": "object"},
            }
        },
    },

    "commits": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "sha": {"type": "keyword"},
                "node_id": {"type": "keyword"},
                "commit": {"type": "object"},     # commit.author/date, commit.committer/date, message, tree...
                "url": {"type": "keyword"},
                "html_url": {"type": "keyword"},
                "comments_url": {"type": "keyword"},
                "author": {"type": "object"},     # author.login, id, ...
                "committer": {"type": "object"},  # committer.login, id, ...
                "parents": {"type": "object"},
                "files_changed": {"type": "keyword"},
                "files_changed_count": {"type": "integer"},
                "stats": {"type": "object"},
            }
        },
    },

    "contributors": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "login": {"type": "keyword"},
                "id": {"type": "long"},
                "html_url": {"type": "keyword"},
                "type": {"type": "keyword"},
                "site_admin": {"type": "boolean"},
                "contributions": {"type": "integer"},
            }
        },
    },

    "prs_with_linked_issues": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "pr_number": {"type": "integer"},
                "title": {"type": "text", "analyzer": "text_en"},
                "author": {"type": "keyword"},
                "state": {"type": "keyword"},
                "merged": {"type": "boolean"},
                "links": {"type": "object"},  # array of link objects
                "url": {"type": "keyword"},
                "created_at": {"type": "date"},
            }
        },
    },

    "issues_closed_by_commits": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "commit_sha": {"type": "keyword"},
                "commit_url": {"type": "keyword"},
                "commit_author": {"type": "keyword"},
                "referenced_repo": {"type": "keyword"},
                "issue_number": {"type": "integer"},
                "issue_author": {"type": "keyword"},
                "reference_type": {"type": "keyword"},
                "has_closing_kw": {"type": "boolean"},
                "would_auto_close": {"type": "boolean"},
            }
        },
    },

    "cross_repo_links": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "source": {"type": "object"},    # source.repo_name, source.type, source.number, source.url, source.created_at
                "reference": {"type": "object"}, # reference.found_in, seen_at, cross_ref_timestamp
                "target": {"type": "object"},    # target.repo_name, type, number, url, created_at, author
            }
        },
    },

    "repo_blame": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "repo_name": {"type": "keyword"},
                "ref": {"type": "keyword"},
                "generated_at": {"type": "date"},
                "error": {"type": "text", "analyzer": "text_en"},
                "files": {
                    "type": "nested",
                    "properties": {
                        "path": {"type": "keyword"},
                        "ref": {"type": "keyword"},
                        "root_commit_oid": {"type": "keyword"},
                        "ranges_count": {"type": "integer"},
                        "total_lines": {"type": "integer"},
                        "authors": {
                            "type": "nested",
                            "properties": {
                                "author": {"type": "keyword"},
                                "total_lines": {"type": "integer"},
                                "ranges": {
                                    "type": "nested",
                                    "properties": {
                                        "start": {"type": "integer"},
                                        "end": {"type": "integer"},
                                        "count": {"type": "integer"},
                                        "age": {"type": "integer"},
                                        "commit_sha": {"type": "keyword"},
                                        "committed_date": {"type": "date"},
                                        "message": {"type": "text", "analyzer": "text_en"},
                                        "matching_commit": {
                                            "type": "object",
                                            "properties": {
                                                "repo_name": {"type": "keyword"},
                                                "sha": {"type": "keyword"},
                                                "html_url": {"type": "keyword"},
                                                "author_login": {"type": "keyword"},
                                                "commit_author": {"type": "object"},
                                                "files_changed": {"type": "keyword"},
                                                "files_changed_count": {"type": "integer"},
                                            }
                                        },
                                    }
                                },
                            },
                        },
                        "examples": {
                            "type": "nested",
                            "properties": {
                                "lines": {
                                    "type": "object",
                                    "properties": {
                                        "start": {"type": "integer"},
                                        "end": {"type": "integer"},
                                        "count": {"type": "integer"},
                                    },
                                },
                                "commit_sha": {"type": "keyword"},
                                "committed_date": {"type": "date"},
                                "who": {"type": "keyword"},
                                "message": {"type": "text", "analyzer": "text_en"},
                                "matching_commit": {
                                    "type": "object",
                                    "properties": {
                                        "repo_name": {"type": "keyword"},
                                        "sha": {"type": "keyword"},
                                        "html_url": {"type": "keyword"},
                                        "author_login": {"type": "keyword"},
                                        "commit_author": {"type": "object"},
                                        "files_changed": {"type": "keyword"},
                                        "files_changed_count": {"type": "integer"},
                                    },
                                },
                            },
                        },
                    },
                },
            }
        },
    },
}


# file -> index routing and ids
def id_commits(doc: Dict[str, Any]) -> Optional[str]:
    """Use the commit SHA when present, otherwise fall back to a stable hash."""
    return doc.get("sha") or stable_hash_id(doc, "commit:")

def id_pull_requests(doc: Dict[str, Any]) -> Optional[str]:
    """Build IDs using repo_name#pr#number to keep PR documents unique."""
    rn = doc.get("repo_name")
    num = doc.get("number")
    return f"{rn}#pr#{num}" if rn and num is not None else stable_hash_id(doc, "pr:")

def id_issues(doc: Dict[str, Any]) -> Optional[str]:
    """Return repo_name#issue#number ids for issues (or hashed fallback)."""
    rn = doc.get("repo_name")
    num = doc.get("number")
    return f'{rn}#issue#{num}' if rn and num is not None else stable_hash_id(doc, "issue:")

def id_prs_with_linked_issues(doc: Dict[str, Any]) -> Optional[str]:
    """IDs for PR-link docs combine repo name with PR number."""
    rn = doc.get("repo_name")
    num = doc.get("pr_number") or doc.get("number")
    return f"{rn}#prlinks#{num}" if rn and num is not None else stable_hash_id(doc, "prlinks:")

def id_issues_closed_by_commits(doc: Dict[str, Any]) -> Optional[str]:
    """Combine repo, issue number, and commit SHA for closing references."""
    rn = doc.get("repo_name")
    num = doc.get("issue_number") or doc.get("number")
    sha = doc.get("commit_sha")
    if rn and num is not None and sha:
        return f"{rn}#closedby#{num}#{sha}"
    return stable_hash_id(doc, "closedby:")

def id_cross_repo_links(doc: Dict[str, Any]) -> Optional[str]:
    """Hash the source→target tuple to ensure identical cross-links dedupe cleanly."""
    s = doc.get("source", {}) or {}
    t = doc.get("target", {}) or {}
    base = f"{s.get('repo_name')}:{s.get('type')}:{s.get('number')}->{t.get('repo_name')}:{t.get('type')}:{t.get('number')}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def id_contributors(doc: Dict[str, Any]) -> Optional[str]:
    """Return repo_name#contrib#login IDs for contributors."""
    rn = doc.get("repo_name")
    login = doc.get("login")
    return f"{rn}#contrib#{login}" if rn and login else stable_hash_id(doc, "contrib:")

def id_repo_blame(doc: Dict[str, Any]) -> Optional[str]:
    """Blame documents are keyed by repo+ref for deterministic updates."""
    rn = doc.get("repo_name")
    ref = doc.get("ref")
    return f"{rn}#blame#{ref}" if rn and ref else stable_hash_id(doc, "blame:")


FILE_TO_INDEX: Dict[str, Tuple[str, Any]] = {
    "repo_meta.json": ("repo_meta", lambda d: d.get("repo_name") or stable_hash_id(d, "meta:")),
    "issues.json": ("issues", id_issues),
    "pull_requests.json": ("pull_requests", id_pull_requests),
    "commits.json": ("commits", id_commits),
    "contributors.json": ("contributors", id_contributors),
    "prs_with_linked_issues.json": ("prs_with_linked_issues", id_prs_with_linked_issues),
    "issues_closed_by_commits.json": ("issues_closed_by_commits", id_issues_closed_by_commits),
    "cross_repo_links.json": ("cross_repo_links", id_cross_repo_links),
    "repo_blame.json": ("repo_blame", id_repo_blame),
}


# scanning & indexing
def scan_and_index(es: ESClient, data_dir: Path, index_prefix: str,
                   dry_run: bool = False, batch_size: int = 1000) -> None:
    """Iterate over repo folders and stream JSON docs into their target indices."""
    if not data_dir.exists():
        print(f"Data dir not found: {data_dir}")
        return

    # Ensure indices exist (with mappings) before indexing to avoid runtime schema surprises.
    for _, (idx_name, _) in FILE_TO_INDEX.items():
        full = f"{index_prefix}{idx_name}"
        es.ensure_index(full, MAPPINGS.get(idx_name))
    print("Ensured indices:", ", ".join(f"{index_prefix}{nm}" for nm, _ in FILE_TO_INDEX.values()))

    repo_dirs = [p for p in data_dir.iterdir() if p.is_dir()]
    if not repo_dirs:
        print(f"No repo subfolders found in {data_dir}. Expected ./output/owner_repo/.")
        return

    total_ok = total_fail = 0
    started = time.time()

    for repo_dir in sorted(repo_dirs):
        repo_name = folder_repo_name(repo_dir)
        print(f"\n=== {repo_name} ===")

        for filename, (idx_base, id_fn) in FILE_TO_INDEX.items():
            fpath = repo_dir / filename
            index_name = f"{index_prefix}{idx_base}"

            if not fpath.exists():
                continue

            print(f"  -> {filename} -> {index_name}")

            def gen_docs() -> Iterable[Dict[str, Any]]:
                for doc in iter_json(fpath):
                    # normalize top-level repo name
                    ensure_repo_name_field(doc, repo_name)
                    yield doc

            if dry_run:
                cnt = sum(1 for _ in gen_docs())
                print(f"     (dry-run) parsed {cnt} docs")
            else:
                ok, fail = es.bulk_index(index=index_name, docs=gen_docs(), id_func=id_fn, batch_size=batch_size)
                print(f"     indexed: ok={ok} fail={fail}")
                total_ok += ok
                total_fail += fail

    dur = time.time() - started
    print(f"\nDone. Total ok={total_ok}, fail={total_fail}, took {dur:.1f}s")


# entrypoint
def main() -> None:
    """CLI entrypoint for the indexing workflow."""
    args = get_args()
    # apply HARDLOCK
    if HARDLOCK:
        data_dir = Path(HARDCODED_DATA_DIR)
        es_url = HARDCODED_ES_URL
        username = HARDCODED_ES_USERNAME
        password = HARDCODED_ES_PASSWORD
        api_key = HARDCODED_ES_API_KEY
        verify_tls = HARDCODED_VERIFY_TLS
        prefix = HARDCODED_INDEX_PREFIX
        batch_size = HARDCODED_BATCH_SIZE
        dry_run = False
    else:
        data_dir = Path(args.data_dir)
        es_url = args.es_url
        username = args.username
        password = args.password
        api_key = args.api_key
        verify_tls = args.verify_tls
        prefix = args.prefix
        batch_size = args.batch_size
        dry_run = args.dry_run

    es = ESClient(
        base_url=es_url,
        username=username,
        password=password,
        api_key=api_key,
        verify_tls=verify_tls,
    )

    scan_and_index(
        es,
        data_dir=data_dir,
        index_prefix=prefix,
        dry_run=dry_run,
        batch_size=batch_size,
    )


if __name__ == "__main__":
    main()
