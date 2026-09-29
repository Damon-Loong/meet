"""AFB vector API adapter; callers must authorize a shared scope before use.

This is not wired into production. Namespace filtering is defense in depth, not
access control: the platform's Agent keys can access all collections.
"""

import hashlib
import json
import re
from urllib.parse import urlsplit

import requests


class KnowledgeError(Exception):
    """Report failures without exposing keys, documents or provider responses."""


def shared_namespace(tenant_id: str, shared_scope_id: str) -> str:
    """Build a stable namespace from trusted IDs, never from participant names."""
    if not tenant_id.strip() or not shared_scope_id.strip():
        raise ValueError("A tenant and an authorized shared scope are required")
    value = json.dumps([tenant_id, shared_scope_id], ensure_ascii=False)
    return "meet_" + hashlib.sha256(value.encode()).hexdigest()


def transcript_documents(
    transcript: str, *, namespace: str, recording_id: str, source_name: str
) -> list[dict]:
    """Prepare deterministic original-text chunks, without generating facts.

    Different source versions get different IDs. Replacing/deleting older versions
    needs a separate lifecycle workflow before this adapter is enabled in production.
    """
    if not transcript.strip() or not recording_id.strip() or not namespace.strip():
        raise ValueError("Transcript, recording ID and namespace are required")
    digest = hashlib.sha256(transcript.encode()).hexdigest()
    identity = json.dumps([namespace, recording_id, digest], ensure_ascii=False)
    # Use a compact ID: the live backend rejected the former 75-character ID.
    # A 128-bit digest still scopes the identity to source, namespace and version.
    prefix = hashlib.sha256(identity.encode()).hexdigest()[:32]
    chunks = [transcript[i : i + 2400] for i in range(0, len(transcript), 2400)]
    return [
        {
            "id": f"meet_{prefix}_{number:05d}",
            "content": chunk,
            "namespace": namespace,
            "source_id": recording_id,
            "source_name": source_name,
            "active": True,
            "metadata": {
                "kind": "meeting_transcript",
                "source_sha256": digest,
                "chunk_index": number,
                "char_start": number * 2400,
            },
        }
        for number, chunk in enumerate(chunks)
    ]


class MeetingKnowledgeClient:
    """Use only documented AFB endpoints with timeouts and explicit scoping."""

    def __init__(
        self,
        *,
        api_key: str,
        collection_id: str,
        namespace: str,
        base_url: str = "https://afb.mbmzone.com/afb-agent/v1",
        session=None,
    ):
        """Keep credentials server-side; reject insecure or ambiguous URLs."""
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("A trusted HTTPS API base URL is required")
        if not api_key.strip() or not namespace.strip():
            raise ValueError("API key and explicit namespace are required")
        if not re.fullmatch(r"vc_[A-Za-z0-9_-]+", collection_id):
            raise ValueError("Invalid collection ID")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._collection = collection_id
        self._namespace = namespace
        self._session = session or requests.Session()

    def _request(self, method, path, payload=None):
        try:
            response = self._session.request(
                method,
                self._base + path,
                headers={"Authorization": f"Bearer {self._key}"},
                json=payload,
                timeout=(5, 30),
                allow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                raise KnowledgeError("Knowledge API request failed")
            data = response.json()
            if not isinstance(data, dict):
                raise KnowledgeError("Invalid knowledge API response")
            return data
        except (requests.RequestException, ValueError):
            raise KnowledgeError("Knowledge API unavailable or invalid") from None

    def submit(self, documents: list[dict]) -> str:
        """Queue scoped chunks; a job ID is NOT evidence of completed indexing."""
        if not documents:
            raise ValueError("Documents must not be empty")
        ids = set()
        for document in documents:
            if (
                document.get("namespace") != self._namespace
                or not document.get("content", "").strip()
                or not document.get("id")
                or document["id"] in ids
            ):
                raise ValueError("Invalid, duplicate or out-of-scope document")
            ids.add(document["id"])
        result = self._request(
            "POST",
            f"/vector-collections/{self._collection}/documents",
            {"documents": documents, "reset": False},
        )
        job_id = result.get("job_id", "")
        if not isinstance(job_id, str) or not re.fullmatch(r"vwj_[\w-]+", job_id):
            raise KnowledgeError("Write job ID missing or invalid")
        return job_id

    def job_status(self, job_id: str) -> dict:
        """Return counts and state only; do not leak per-document error bodies."""
        if not re.fullmatch(r"vwj_[\w-]+", job_id):
            raise ValueError("Invalid job ID")
        result = self._request("GET", f"/vector-write-jobs/{job_id}")
        job = result.get("job")
        if not isinstance(job, dict) or job.get("id") != job_id:
            raise KnowledgeError("Invalid write job response")
        return {
            key: job.get(key)
            for key in ("id", "status", "total", "processed", "upserted", "failed")
        }

    def query(self, query: str, *, top_k: int = 5) -> list[dict]:
        """Retrieve within one authorized scope; reject cross-scope responses."""
        if not query.strip() or not 1 <= top_k <= 10:
            raise ValueError("A query and top_k between 1 and 10 are required")
        result = self._request(
            "POST",
            f"/vector-collections/{self._collection}/documents/query",
            {
                "query": query,
                "mode": "hybrid",
                "namespace": self._namespace,
                "top_k": top_k,
            },
        )
        hits = result.get("results")
        if not isinstance(hits, list):
            raise KnowledgeError("Invalid query response")
        for hit in hits:
            if (
                not isinstance(hit, dict)
                or hit.get("namespace") != self._namespace
                or not isinstance(hit.get("content"), str)
                or not isinstance(hit.get("source_id"), str)
                or not hit["source_id"]
            ):
                raise KnowledgeError("Unscoped or unattributed query result")
        return hits[:top_k]
