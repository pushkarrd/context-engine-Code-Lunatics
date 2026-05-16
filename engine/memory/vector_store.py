"""ChromaDB wrapper for incident fingerprint storage and retrieval."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Strip None values — ChromaDB only accepts str, int, float, bool."""
    clean: dict[str, Any] = {}
    for k, v in metadata.items():
        if v is None:
            clean[k] = ""
        elif isinstance(v, (str, int, float, bool)):
            clean[k] = v
        else:
            clean[k] = str(v)
    return clean


class VectorStore:
    """ChromaDB-backed vector store for incident fingerprints."""

    def __init__(self, persist_dir: str = "./data/chroma") -> None:
        self.persist_dir = persist_dir
        self.dimension = 12
        os.makedirs(persist_dir, exist_ok=True)

        try:
            import chromadb

            self.client = chromadb.PersistentClient(path=persist_dir)
            collection_name = f"incident_fingerprints_v{self.dimension}"
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine", "dimension": self.dimension},
            )
        except Exception as exc:
            logger.exception("Failed to initialize ChromaDB: %s", exc)
            raise

    def store_fingerprint(
        self,
        incident_id: str,
        fingerprint_text: str,
        fingerprint_vector: list[float],
        metadata: dict[str, Any],
    ) -> None:
        if not incident_id or not fingerprint_vector:
            return

        try:
            self.collection.upsert(
                ids=[incident_id],
                documents=[fingerprint_text or ""],
                embeddings=[fingerprint_vector],
                metadatas=[_sanitize_metadata(metadata or {})],
            )
        except Exception as exc:
            logger.exception("Failed to store fingerprint %s: %s", incident_id, exc)

    def find_similar(
        self,
        query_text: str,
        query_vector: list[float],
        n_results: int = 5,
        exclude_incident_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not query_vector:
            return []

        # ChromaDB wants exactly ONE of query_embeddings OR query_texts — not both
        total = self.collection.count()
        if total == 0:
            return []

        # n_results can't exceed total stored
        safe_n = min(n_results, total)

        try:
            results = self.collection.query(
                query_embeddings=[query_vector],
                n_results=safe_n,
                include=["distances", "metadatas", "documents"],
            )
        except Exception as exc:
            logger.exception("Failed to query similar fingerprints: %s", exc)
            return []

        ids = results.get("ids", [[]])[0] if results else []
        distances = results.get("distances", [[]])[0] if results else []
        metas = results.get("metadatas", [[]])[0] if results else []

        matches: list[dict[str, Any]] = []
        for idx, incident_id in enumerate(ids):
            if exclude_incident_id and incident_id == exclude_incident_id:
                continue

            distance = distances[idx] if idx < len(distances) else None
            if distance is None:
                continue

            similarity = max(0.0, 1.0 - float(distance))
            metadata = metas[idx] if idx < len(metas) else {}
            matches.append({
                "incident_id": incident_id,
                "similarity": similarity,
                "metadata": metadata,
            })

        return matches

    def get_by_incident_id(self, incident_id: str) -> dict[str, Any] | None:
        if not incident_id:
            return None

        try:
            results = self.collection.get(
                ids=[incident_id],
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception as exc:
            logger.exception("Failed to fetch fingerprint %s: %s", incident_id, exc)
            return None

        if not results or not results.get("ids"):
            return None

        return {
            "incident_id": incident_id,
            "document": results.get("documents", [None])[0],
            "metadata": results.get("metadatas", [None])[0],
            "embedding": results.get("embeddings", [None])[0],
        }

    def count(self) -> int:
        try:
            return int(self.collection.count())
        except Exception as exc:
            logger.exception("Failed to count fingerprints: %s", exc)
            return 0