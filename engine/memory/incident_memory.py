"""Incident memory and similarity recall."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from engine.memory.fingerprint import BehavioralFingerprint, FingerprintExtractor

logger = logging.getLogger(__name__)


def _parse_ts(ts: str | datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _text_similarity(a: str, b: str) -> float:
    tokens_a = set(re.findall(r"[a-z0-9_]+", (a or "").lower()))
    tokens_b = set(re.findall(r"[a-z0-9_]+", (b or "").lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    return len(overlap) / len(union) if union else 0.0


class IncidentMemory:
    """Stores incident fingerprints and supports similarity recall."""

    def __init__(self, vector_store: Any, fingerprint_extractor: Any, alias_registry: Any) -> None:
        self.vector_store = vector_store
        self.fingerprint_extractor = fingerprint_extractor
        self.alias_registry = alias_registry
        self._incidents: dict[str, dict[str, Any]] = {}
        self._remediations: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def remember_incident(
        self,
        incident_id: str,
        incident_event: dict[str, Any],
        related_events: list[dict[str, Any]],
        remediation: dict[str, Any] | None = None,
    ) -> None:
        if not incident_id:
            return

        resolved_signal = self._resolve_event(incident_event)
        resolved_events = self._resolve_events(related_events)

        fingerprint = self.fingerprint_extractor.extract(
            incident_id,
            resolved_signal,
            resolved_events,
            remediation,
        )
        fingerprint_text = self.fingerprint_extractor.to_text(fingerprint)
        fingerprint_vector = self.fingerprint_extractor.to_vector(fingerprint)

        metadata = {
            "pattern_sequence": "->".join(fingerprint.get("pattern_sequence", [])),
            "remediation_type": fingerprint.get("remediation_type") or "",
            "resolution_time_mins": fingerprint.get("resolution_time_mins") or 0.0,
            "severity": fingerprint.get("severity", ""),
            "trigger_type": fingerprint.get("trigger_type", ""),
            "family_hint": fingerprint.get("family_hint", ""),
        }

        if hasattr(self.vector_store, "store_fingerprint"):
            self.vector_store.store_fingerprint(
                incident_id,
                fingerprint_text,
                fingerprint_vector,
                metadata,
            )

        with self._lock:
            self._incidents[incident_id] = {
                "fingerprint": fingerprint,
                "text": fingerprint_text,
                "vector": fingerprint_vector,
                "metadata": metadata,
                "signal": resolved_signal,
                "updated_at": datetime.now(timezone.utc),
            }

    def record_remediation(self, incident_id: str, remediation_event: dict[str, Any]) -> None:
        if not incident_id or not remediation_event:
            return
        with self._lock:
            self._remediations[incident_id] = dict(remediation_event)
            if incident_id in self._incidents:
                self._incidents[incident_id]["remediation"] = dict(remediation_event)

    def recall_similar(
        self,
        incident_event: dict[str, Any],
        related_events: list[dict[str, Any]],
        n: int = 5,
    ) -> list[dict[str, Any]]:
        incident_id = incident_event.get("incident_id", "")
        resolved_signal = self._resolve_event(incident_event)
        resolved_events = self._resolve_events(related_events)

        fingerprint = self.fingerprint_extractor.extract(
            incident_id,
            resolved_signal,
            resolved_events,
        )
        query_text = self.fingerprint_extractor.to_text(fingerprint)
        query_vector = self.fingerprint_extractor.to_vector(fingerprint)

        combined: dict[str, dict[str, Any]] = {}

        vector_matches = []
        if hasattr(self.vector_store, "find_similar"):
            vector_matches = self.vector_store.find_similar(
                query_text,
                query_vector,
                n_results=max(n, 5),
                exclude_incident_id=incident_id or None,
            )

        for match in vector_matches:
            mid = match.get("incident_id")
            if not mid or mid == incident_id:
                continue
            combined.setdefault(mid, {
                "vector": 0.0,
                "text": 0.0,
                "metadata": match.get("metadata", {}),
            })
            combined[mid]["vector"] = float(match.get("similarity", 0.0))
            if match.get("metadata") and not combined[mid].get("metadata"):
                combined[mid]["metadata"] = match.get("metadata", {})

        text_matches = self._query_text_matches(query_text, n, incident_id)
        for match in text_matches:
            mid = match.get("incident_id")
            if not mid or mid == incident_id:
                continue
            combined.setdefault(mid, {
                "vector": 0.0,
                "text": 0.0,
                "metadata": match.get("metadata", {}),
            })
            combined[mid]["text"] = max(combined[mid]["text"], float(match.get("similarity", 0.0)))
            if match.get("metadata") and not combined[mid].get("metadata"):
                combined[mid]["metadata"] = match.get("metadata", {})

        if not text_matches:
            for mid, entry in combined.items():
                doc = self._get_document(mid)
                entry["text"] = _text_similarity(query_text, doc)

        with self._lock:
            for mid, data in self._incidents.items():
                if mid == incident_id or mid in combined:
                    continue
                stored_fp = data.get("fingerprint")
                if stored_fp:
                    similarity = self.fingerprint_extractor.similarity(fingerprint, stored_fp)
                else:
                    similarity = 0.0
                combined[mid] = {
                    "vector": similarity,
                    "text": _text_similarity(query_text, data.get("text", "")),
                    "metadata": data.get("metadata", {}),
                }

        scored: list[dict[str, Any]] = []
        for mid, entry in combined.items():
            metadata = entry.get("metadata", {})
            
            # Base similarity: combined vector and text scores
            vector_score = float(entry.get("vector", 0.0))
            text_score = float(entry.get("text", 0.0))
            base_similarity = 0.6 * vector_score + 0.4 * text_score
            
            # Check for family match (huge boost)
            query_family = fingerprint.get("family_hint", "")
            stored_family = metadata.get("family_hint", "")
            if query_family and stored_family and query_family == stored_family:
                # Family match - add significant boost
                final_similarity = min(1.0, base_similarity + 0.35)
            else:
                # Non-family: use attribute-based boost
                boost = self._compute_similarity_boost(fingerprint, metadata)
                final_similarity = min(1.0, base_similarity + boost)
            
            rationale = self._build_rationale(mid, metadata, final_similarity)
            scored.append({
                "incident_id": mid,
                "past_incident_id": mid,
                "similarity": final_similarity,
                "rationale": rationale,
                "metadata": metadata,
            })

        scored.sort(key=lambda m: m.get("similarity", 0.0), reverse=True)
        return scored[: max(n, 0)]

    def get_successful_remediations(
        self,
        incident_id: str,
        similar_incidents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        for match in similar_incidents:
            mid = match.get("incident_id")
            if not mid:
                continue
            remediation = self._remediations.get(mid)
            if not remediation:
                continue
            outcome = str(remediation.get("outcome", "")).lower()
            if outcome and outcome not in {"resolved", "success"}:
                continue
            suggestions.append({
                "action": remediation.get("action", "unknown"),
                "target": remediation.get("target", ""),
                "historical_outcome": remediation.get("outcome", "unknown"),
                "confidence": float(match.get("similarity", 0.0)),
            })
            if suggestions:
                break
        return suggestions

    def count(self) -> int:
        if hasattr(self.vector_store, "count"):
            try:
                return int(self.vector_store.count())
            except Exception:
                return 0
        return len(self._incidents)

    def _enrich_related_events(
        self,
        service: str,
        ts: datetime,
        event_store: Any,
        window_minutes: int = 10,
    ) -> list[dict[str, Any]]:
        if not service or not event_store:
            return []

        canonical = self.alias_registry.resolve(service) if self.alias_registry else service
        service_scope: str | list[str] = canonical
        if canonical and hasattr(self.alias_registry, "get_all_aliases"):
            service_scope = self.alias_registry.get_all_aliases(canonical)

        if hasattr(event_store, "query_time_window"):
            events = event_store.query_time_window(service_scope, ts, window_minutes=window_minutes)
        else:
            events = []

        return self._resolve_events(events)

    def _resolve_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if not event:
            return {}
        if self.alias_registry and hasattr(self.alias_registry, "resolve_event"):
            return self.alias_registry.resolve_event(event)
        return dict(event)

    def _resolve_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        return [self._resolve_event(e) for e in events]

    def _get_document(self, incident_id: str) -> str:
        if not incident_id or not hasattr(self.vector_store, "get_by_incident_id"):
            return ""
        record = self.vector_store.get_by_incident_id(incident_id)
        if not record:
            return ""
        return str(record.get("document") or "")

    def _query_text_matches(self, query_text: str, n: int, exclude_incident_id: str) -> list[dict[str, Any]]:
        collection = getattr(self.vector_store, "collection", None)
        if not collection:
            return []

        try:
            total = int(collection.count())
        except Exception:
            total = 0
        if total == 0:
            return []

        safe_n = min(max(n, 5), total)
        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=safe_n,
                include=["distances", "metadatas", "documents"],
            )
        except Exception as exc:
            logger.debug("Text query failed: %s", exc)
            return []

        ids = results.get("ids", [[]])[0] if results else []
        distances = results.get("distances", [[]])[0] if results else []
        metas = results.get("metadatas", [[]])[0] if results else []

        matches: list[dict[str, Any]] = []
        for idx, mid in enumerate(ids):
            if not mid or mid == exclude_incident_id:
                continue
            distance = distances[idx] if idx < len(distances) else None
            if distance is None:
                continue
            similarity = max(0.0, 1.0 - float(distance))
            metadata = metas[idx] if idx < len(metas) else {}
            matches.append({
                "incident_id": mid,
                "similarity": similarity,
                "metadata": metadata,
            })
        return matches

    def _compute_similarity_boost(self, query_fp: BehavioralFingerprint, stored_metadata: dict[str, Any]) -> float:
        """Compute bonus points for attribute matches (trigger, severity, remediation outcome).
        
        Args:
            query_fp: Query fingerprint
            stored_metadata: Metadata from stored incident
            
        Returns:
            Boost score 0.0-0.40 to add to base similarity
        """
        boost = 0.0
        
        # Criterion 1: Matching trigger types
        query_trigger = query_fp.get("trigger_type", "")
        stored_trigger = stored_metadata.get("trigger_type", "")
        if query_trigger and stored_trigger and query_trigger == stored_trigger:
            boost += 0.10
        
        # Criterion 2: Matching severity
        query_severity = query_fp.get("severity", "")
        stored_severity = stored_metadata.get("severity", "")
        if query_severity and stored_severity and query_severity == stored_severity:
            boost += 0.10
        
        # Criterion 3: Matching pattern sequence
        query_pattern = query_fp.get("pattern_sequence", [])
        stored_pattern_str = stored_metadata.get("pattern_sequence", "")
        if query_pattern and stored_pattern_str:
            stored_pattern = stored_pattern_str.split("->")
            pattern_overlap = len([p for p in query_pattern if p in stored_pattern])
            if pattern_overlap >= 2:
                boost += 0.08
        
        # Criterion 4: Matching remediation type
        query_remediation = query_fp.get("remediation_type")
        stored_remediation = stored_metadata.get("remediation_type")
        if query_remediation and stored_remediation and query_remediation == stored_remediation:
            boost += 0.08
        
        # Criterion 5: Fast resolution
        resolution_time = stored_metadata.get("resolution_time_mins")
        if resolution_time and float(resolution_time) < 30:
            boost += 0.04
        
        return min(0.40, boost)

    def _build_rationale(self, incident_id: str, metadata: dict[str, Any], similarity: float) -> str:
        pattern = metadata.get("pattern_sequence")
        if isinstance(pattern, str) and pattern:
            pattern_text = pattern
        elif isinstance(pattern, list):
            pattern_text = "->".join(pattern)
        else:
            with self._lock:
                stored = self._incidents.get(incident_id, {})
                pattern_text = stored.get("metadata", {}).get("pattern_sequence", "")
        if not pattern_text:
            pattern_text = "unknown"

        remediation = metadata.get("remediation_type")
        if not remediation:
            with self._lock:
                stored = self._incidents.get(incident_id, {})
                remediation = stored.get("metadata", {}).get("remediation_type", "unknown")

        return (
            f"Similar pattern: {pattern_text}. "
            f"Previously resolved by {remediation} (confidence: {similarity:.2f})"
        )
