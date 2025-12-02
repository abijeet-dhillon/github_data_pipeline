"""Elasticsearch mappings and ID helpers for the indexing workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Tuple

COMMON_SETTINGS: Dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "text_en": {
                    "type": "standard",
                    "stopwords": "_english_",
                }
            }
        },
    }
}


def stable_hash_id(doc: Dict[str, Any], salt: str = "") -> str:
    """Return a deterministic SHA1 hash for a document (optionally salted)."""

    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1((salt + raw).encode("utf-8")).hexdigest()


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
                "owner": {"type": "object"},
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
            },
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
            },
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
                "head": {"type": "object"},
                "base": {"type": "object"},
                "_links": {"type": "object"},
                "author_association": {"type": "keyword"},
                "auto_merge": {"type": "object"},
            },
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
                "commit": {"type": "object"},
                "url": {"type": "keyword"},
                "html_url": {"type": "keyword"},
                "comments_url": {"type": "keyword"},
                "author": {"type": "object"},
                "committer": {"type": "object"},
                "parents": {"type": "object"},
                "files_changed": {"type": "keyword"},
                "files_changed_count": {"type": "integer"},
                "stats": {"type": "object"},
            },
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
            },
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
                "links": {"type": "object"},
                "url": {"type": "keyword"},
                "created_at": {"type": "date"},
            },
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
            },
        },
    },
    "cross_repo_links": {
        **COMMON_SETTINGS,
        "mappings": {
            "dynamic": True,
            "properties": {
                "source": {"type": "object"},
                "reference": {"type": "object"},
                "target": {"type": "object"},
            },
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
                                            },
                                        },
                                    },
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
            },
        },
        "settings": {
            **COMMON_SETTINGS["settings"],
            # Large blame documents can exceed ES nested limits; raise safely.
            "index.mapping.nested_objects.limit": 150000,
        },
    },
}


def id_commits(doc: Dict[str, Any]) -> Optional[str]:
    return doc.get("sha") or stable_hash_id(doc, "commit:")


def id_pull_requests(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    num = doc.get("number")
    return f"{rn}#pr#{num}" if rn and num is not None else stable_hash_id(doc, "pr:")


def id_issues(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    num = doc.get("number")
    return f"{rn}#issue#{num}" if rn and num is not None else stable_hash_id(doc, "issue:")


def id_prs_with_linked_issues(doc: Dict[str, Any]) -> Optional[str]:
    rn = doc.get("repo_name")
    num = doc.get("pr_number") or doc.get("number")
    return f"{rn}#prlinks#{num}" if rn and num is not None else stable_hash_id(doc, "prlinks:")


def id_issues_closed_by_commits(doc: Dict[str, Any]) -> Optional[str]:
    repo_name = doc.get("repo_name")
    issue = doc.get("issue_number") or doc.get("number")
    sha = doc.get("commit_sha")
    if repo_name and issue is not None and sha:
        return f"{repo_name}#closedby#{issue}#{sha}"
    return stable_hash_id(doc, "closedby:")


def id_cross_repo_links(doc: Dict[str, Any]) -> Optional[str]:
    source = doc.get("source") or {}
    target = doc.get("target") or {}
    base = (
        f"{source.get('repo_name')}:{source.get('type')}:{source.get('number')}->"
        f"{target.get('repo_name')}:{target.get('type')}:{target.get('number')}"
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def id_repo_blame(doc: Dict[str, Any]) -> Optional[str]:
    repo_name = doc.get("repo_name")
    ref = doc.get("ref")
    files = doc.get("files") or []
    if repo_name and ref:
        if len(files) == 1 and isinstance(files[0], dict):
            path = files[0].get("path")
            if path:
                digest = hashlib.sha1(f"{repo_name}:{ref}:{path}".encode("utf-8")).hexdigest()
                return f"{repo_name}#blame#{ref}#file#{digest}"
        chunk_id = doc.get("chunk_id")
        if chunk_id is not None:
            return f"{repo_name}#blame#{ref}#chunk#{chunk_id}"
        return f"{repo_name}#blame#{ref}"
    return stable_hash_id(doc, "blame:")


def id_contributors(doc: Dict[str, Any]) -> Optional[str]:
    repo_name = doc.get("repo_name")
    login = doc.get("login")
    if repo_name and login:
        return f"{repo_name}#contrib#{login}"
    return stable_hash_id(doc, "contrib:")


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


__all__ = [
    "COMMON_SETTINGS",
    "MAPPINGS",
    "FILE_TO_INDEX",
    "stable_hash_id",
    "id_commits",
    "id_pull_requests",
    "id_issues",
    "id_prs_with_linked_issues",
    "id_issues_closed_by_commits",
    "id_cross_repo_links",
    "id_repo_blame",
    "id_contributors",
]
