"""Context reconstruction orchestrator."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

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


class ContextBuilder:
    """Orchestrates reconstruct_context across subsystems."""

    def __init__(self, event_store: Any, causal_graph: Any, incident_memory: Any, alias_registry: Any, gemini_client: Any) -> None:
        """Initialize context builder.

        Args:
            event_store: EventStore instance.
            causal_graph: CausalGraph instance.
            incident_memory: IncidentMemory instance.
            alias_registry: AliasRegistry instance.
            gemini_client: Optional Gemini client.
        """
        self.event_store = event_store
        self.causal_graph = causal_graph
        self.incident_memory = incident_memory
        self.alias_registry = alias_registry
        self.gemini_client = gemini_client

    def build(self, signal: dict[str, Any], mode: str = "fast") -> dict[str, Any]:
        """Build the full incident context using causal chains as primary filter.

        Args:
            signal: IncidentSignal dict.
            mode: "fast" or "deep".

        Returns:
            Context dict with all required fields.
        """
        start = time.monotonic()
        budget_s = 2.0 if mode == "fast" else 6.0

        context: dict[str, Any] = {
            "related_events": [],
            "causal_chain": [],
            "similar_past_incidents": [],
            "suggested_remediations": [],
            "confidence": 0.0,
            "explain": "",
        }

        try:
            incident_id = signal.get("incident_id", "")
            service = signal.get("service", "")
            canonical_service = self.alias_registry.resolve(service) if service else service
            signal_ts = _parse_ts(signal.get("ts"))

            logger.debug("context_builder.start incident_id=%s mode=%s", incident_id, mode)

            # === PRIMARY: Build causal chain first (this is the strongest signal) ===
            max_depth = 3 if mode == "fast" else 5
            causal_chain = []
            causal_event_ids = set()
            try:
                if hasattr(self.causal_graph, "get_causal_chain"):
                    causal_chain = self.causal_graph.get_causal_chain(incident_id, max_depth=max_depth)
                    # Extract event IDs from causal chain for prioritization
                    for edge in causal_chain:
                        causal_event_ids.add(edge.get("cause_id", ""))
                        causal_event_ids.add(edge.get("effect_id", ""))
            except Exception as exc:
                logger.exception("Failed to build causal chain: %s", exc)

            context["causal_chain"] = causal_chain

            # === SECONDARY: Query related events with time window ===
            related_events = []
            try:
                if hasattr(self.event_store, "query_time_window"):
                    service_scope = canonical_service
                    if canonical_service and hasattr(self.alias_registry, "get_all_aliases"):
                        service_scope = self.alias_registry.get_all_aliases(canonical_service)
                    # Expand time window for deep mode to capture more context
                    window_mins = 20 if mode == "deep" else 15
                    related_events = self.event_store.query_time_window(
                        service_scope,
                        signal_ts,
                        window_minutes=window_mins,
                    )
                if not related_events and hasattr(self.event_store, "get_events_for_incident"):
                    related_events = self.event_store.get_events_for_incident(incident_id, window_minutes=12)
            except Exception as exc:
                logger.exception("Failed to query related events: %s", exc)

            # === FILTER & RANK: Use causal chain IDs as primary signal ===
            if related_events and hasattr(self.alias_registry, "resolve_event"):
                related_events = [self.alias_registry.resolve_event(e) for e in related_events]
            
            # Rank events using causal chain priority
            try:
                from engine.reconstruction.event_ranker import EventRanker
                related_events = EventRanker.rank_events(
                    related_events,
                    incident_ts=signal_ts,
                    causal_chain_ids=list(causal_event_ids),
                    limit=8 if mode == "deep" else 5,  # Very selective: top 5 events only in fast mode
                )
            except Exception as exc:
                logger.exception("Failed to rank events: %s", exc)

            context["related_events"] = related_events

            # Store fingerprint for this incident so future recall works
            if incident_id:
                try:
                    if hasattr(self.incident_memory, "remember_incident"):
                        self.incident_memory.remember_incident(
                            incident_id,
                            signal,
                            related_events,
                        )
                except Exception as exc:
                    logger.exception("Failed to store incident fingerprint: %s", exc)

            # === SIMILARITY: Find similar past incidents ===
            similar_incidents = []
            try:
                if hasattr(self.incident_memory, "recall_similar"):
                    similar_incidents = self.incident_memory.recall_similar(
                        signal,
                        related_events,
                        n=5,
                    )
            except Exception as exc:
                logger.exception("Failed to recall similar incidents: %s", exc)

            context["similar_past_incidents"] = similar_incidents

            # === REMEDIATION: Build remediation suggestions ===
            remediations = []
            try:
                if hasattr(self.incident_memory, "get_successful_remediations"):
                    remediations = self.incident_memory.get_successful_remediations(
                        incident_id,
                        similar_incidents,
                    )
                # Boost remediation accuracy by ensuring we always return something if similar incidents exist
                if not remediations and similar_incidents:
                    for match in similar_incidents:
                        past_id = match.get("incident_id")
                        if past_id and hasattr(self.incident_memory, "_remediations"):
                            rem = self.incident_memory._remediations.get(past_id)
                            if rem:
                                remediations.append(rem)
                    if remediations:
                        remediations = remediations[:3]
            except Exception as exc:
                logger.exception("Failed to build remediation suggestions: %s", exc)

            context["suggested_remediations"] = remediations

            context["confidence"] = self._compute_confidence(
                causal_chain,
                similar_incidents,
                remediations,
                related_events,
            )

            if self.gemini_client:
                elapsed = time.monotonic() - start
                if elapsed < budget_s - 0.5:
                    try:
                        signal_with_mode = dict(signal)
                        signal_with_mode["mode"] = mode
                        context["explain"] = self.gemini_client.generate_explanation(
                            signal=signal_with_mode,
                            related_events=related_events,
                            causal_chain=causal_chain,
                            similar_incidents=similar_incidents,
                            suggested_remediations=remediations,
                            timeout_s=max(0.5, budget_s - elapsed),
                        )
                    except Exception as exc:
                        logger.exception("Gemini explanation failed: %s", exc)

            force_plain = str(os.environ.get("FORCE_PLAIN_EXPLAIN", "")).lower() in {"1", "true", "yes"}
            if force_plain or not context["explain"]:
                context["explain"] = self._build_plain_explanation(
                    signal,
                    related_events,
                    causal_chain,
                    similar_incidents,
                    remediations,
                )
        except Exception as exc:
            logger.exception("Context build failed: %s", exc)

        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.debug("context_builder.done mode=%s elapsed_ms=%.2f", mode, elapsed_ms)
        return context

    def _build_plain_explanation(
        self,
        signal: dict[str, Any],
        related_events: list[dict[str, Any]],
        causal_chain: list[dict[str, Any]],
        similar_incidents: list[dict[str, Any]],
        remediations: list[dict[str, Any]],
    ) -> str:
        """Template-based explanation for fast mode."""
        raw_service = signal.get("service", "unknown")
        service = self.alias_registry.resolve(raw_service) if raw_service else raw_service
        trigger = signal.get("trigger", "")
        ts = signal.get("ts", "")
        # Pull simple evidence from related events
        deploy_event = next((e for e in related_events if e.get("kind") == "deploy"), None)
        latency_event = next((e for e in related_events if e.get("kind") == "metric" and "latency" in str(e.get("name", "")).lower()), None)
        error_event = next((e for e in related_events if e.get("kind") == "log" and str(e.get("level", "")).lower() == "error"), None)

        root = "unknown"
        if causal_chain:
            root = causal_chain[0].get("cause_id", "unknown")

        match_text = "No similar incidents found."
        if similar_incidents:
            top = similar_incidents[0]
            match_id = top.get("past_incident_id") or top.get("incident_id", "unknown")
            match_text = f"This looks similar to {match_id}."

        remediation_text = "No remediation suggested."
        if remediations:
            top_rem = remediations[0]
            remediation_text = (
                f"Suggested action: {top_rem.get('action', 'unknown')} "
                f"{top_rem.get('target', '')}."
            )

        parts = []
        parts.append(f"Incident in {service} triggered by {trigger} at {ts}.")
        if deploy_event:
            parts.append(
                f"A deploy on {deploy_event.get('service', service)} at {deploy_event.get('ts', '')} is a likely cause."
            )
        elif root != "unknown":
            parts.append(f"Likely root cause: {root}.")

        if latency_event:
            parts.append(
                f"Latency spiked (p99 {latency_event.get('value', '')}) just before the alert."
            )
        if error_event:
            parts.append("Error logs appeared around the same time.")

        parts.append(match_text)
        parts.append(remediation_text)

        return " ".join(p for p in parts if p)

    def _compute_confidence(
        self,
        causal_chain: list[dict[str, Any]],
        similar_incidents: list[dict[str, Any]],
        remediations: list[dict[str, Any]],
        related_events: list[dict[str, Any]],
    ) -> float:
        """Compute overall confidence from multiple signals."""
        chain_conf = 0.0
        if causal_chain:
            confidences = [float(e.get("confidence", 0.0)) for e in causal_chain if "confidence" in e]
            if confidences:
                chain_conf = sum(confidences) / len(confidences)

        similarity_conf = 0.0
        if similar_incidents:
            similarity_conf = float(similar_incidents[0].get("similarity", 0.0))

        evidence_conf = min(len(related_events) / 15.0, 1.0) if related_events else 0.0

        score = (0.45 * chain_conf) + (0.45 * similarity_conf) + (0.10 * evidence_conf)
        if remediations:
            score = min(1.0, score + 0.05)

        return max(0.0, min(score, 1.0))
