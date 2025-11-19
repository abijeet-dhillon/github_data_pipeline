"""Minimal Elasticsearch client wrapper used by the indexing pipeline."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple, Callable

import requests


class ESClient:
    """Thin wrapper around the Elasticsearch HTTP API for indexing documents."""

    def __init__(
        self,
        base_url: str,
        username: Optional[str],
        password: Optional[str],
        api_key: Optional[str],
        verify_tls: bool = True,
    ) -> None:
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
        response = self.session.head(self._url(name), verify=self.verify)
        return response.status_code

    def create_index_with_mapping(self, name: str, body: Dict[str, Any]) -> None:
        response = self.session.put(self._url(name), data=json.dumps(body), verify=self.verify)
        if response.status_code >= 300:
            raise RuntimeError(f"Failed to create index '{name}': {response.status_code} {response.text}")

    def ensure_index(self, name: str, mapping: Optional[Dict[str, Any]]) -> None:
        if self.head_index(name) == 404:
            if mapping is None:
                mapping = {
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {"dynamic": True},
                }
            self.create_index_with_mapping(name, mapping)

    def bulk_index(
        self,
        index: str,
        docs: Iterable[Dict[str, Any]],
        id_func: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        batch_size: int = 1000,
    ) -> Tuple[int, int]:
        """Stream documents into Elasticsearch using the _bulk API."""

        ok_total = 0
        fail_total = 0
        lines: List[str] = []

        def flush() -> None:
            nonlocal ok_total, fail_total, lines
            if not lines:
                return
            payload = "\n".join(lines) + "\n"
            response = self.session.post(
                self._url(f"{index}/_bulk"),
                data=payload,
                headers={"Content-Type": "application/x-ndjson"},
                verify=self.verify,
            )
            lines.clear()
            if response.status_code >= 300:
                print(f"[error] bulk: {response.status_code} {response.text[:300]}")
                fail_total += batch_size
                return

            body = response.json()
            errors = [item for item in body.get("items", []) if any(v.get("error") for v in item.values())]
            ok_total += len(body.get("items", [])) - len(errors)
            fail_total += len(errors)

        count = 0
        for doc in docs:
            doc_id = id_func(doc) if id_func else None
            meta = {"index": {"_index": index}}
            if doc_id:
                meta["index"]["_id"] = doc_id
            lines.append(json.dumps(meta, separators=(",", ":")))
            lines.append(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
            count += 1
            if count % batch_size == 0:
                flush()

        flush()
        return ok_total, fail_total


__all__ = ["ESClient"]
