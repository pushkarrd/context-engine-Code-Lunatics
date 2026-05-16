"""Rankers for events and remediations — filter noise, rank by quality."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from schema import Event, Remediation


def _parse_ts(ts: str | datetime | None) -> datetime:
    """Parse timestamp to datetime."""
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


class EventRanker:
    """Ranks related events by signal quality with temporal decay and causal prioritization."""

    @staticmethod
    def rank_events(
        events: list[Event],
        incident_ts: datetime | str | None = None,
        causal_chain_ids: list[str] | None = None,
        limit: int = 15,
    ) -> list[Event]:
        """Rank events by signal quality, prioritizing causal chain events.

        Args:
            events: Events to rank
            incident_ts: Incident timestamp for temporal decay
            causal_chain_ids: Event IDs in causal chain (prioritized)
            limit: Maximum events to return

        Returns:
            Top-ranked events sorted by composite score
        """
        if not events:
            return []

        causal_chain_ids = causal_chain_ids or []
        incident_ts = _parse_ts(incident_ts)
        
        # Separate causal and non-causal events
        causal_events = []
        non_causal_events = []
        
        for event in events:
            if event.get("id") in causal_chain_ids:
                causal_events.append(event)
            else:
                non_causal_events.append(event)
        
        # Score and sort causal events (these are our primary result set)
        causal_scored = []
        for event in causal_events:
            temporal_score = EventRanker._temporal_proximity_score(event, incident_ts)
            anomaly_score = EventRanker._detect_anomaly_score(event)
            # For causal events, weight is mostly temporal + anomaly (causal is already guaranteed by being in chain)
            composite = temporal_score * 0.6 + anomaly_score * 0.4
            causal_scored.append((event, composite))
        
        causal_scored.sort(key=lambda x: -x[1])
        result = [e for e, _ in causal_scored[:limit]]
        
        # If we have room, add best non-causal events (but only high-quality ones)
        if len(result) < limit:
            non_causal_scored = []
            for event in non_causal_events:
                base_score = EventRanker._score_event(event)
                temporal_score = EventRanker._temporal_proximity_score(event, incident_ts)
                anomaly_score = EventRanker._detect_anomaly_score(event)
                # Much stricter scoring for non-causal events - need high base score + anomaly
                composite = (
                    base_score * 0.4 +
                    temporal_score * 0.3 +
                    anomaly_score * 0.3
                )
                # Only include if composite score is quite high
                if composite > 0.4:
                    non_causal_scored.append((event, composite))
            
            non_causal_scored.sort(key=lambda x: -x[1])
            non_causal_selected = [e for e, _ in non_causal_scored[:max(0, limit - len(result))]]
            result.extend(non_causal_selected)

        return result

    @staticmethod
    def _temporal_proximity_score(event: Event, incident_ts: datetime) -> float:
        """Score based on proximity to incident (exponential decay).
        
        Closer events = higher score. Decays as distance increases.
        
        Args:
            event: Event to score
            incident_ts: Incident timestamp
            
        Returns:
            Score 0.0-1.0
        """
        try:
            event_ts = _parse_ts(event.get("ts"))
            delta_seconds = abs((incident_ts - event_ts).total_seconds())
            
            # Exponential decay: 100% at 0s, 50% at 300s (5min), ~10% at 1200s (20min)
            decay_factor = math.exp(-delta_seconds / 300.0)
            return max(0.0, min(1.0, decay_factor))
        except Exception:
            return 0.5

    @staticmethod
    def _detect_anomaly_score(event: Event) -> float:
        """Detect statistical anomalies in metrics and traces.
        
        Args:
            event: Event to analyze
            
        Returns:
            Anomaly score 0.0-1.0
        """
        kind = event.get("kind", "")
        data = event.get("data", {})
        
        anomaly_score = 0.0
        
        # Metric anomalies
        if kind == "metric":
            value = event.get("value") or data.get("value")
            try:
                val = float(value) if value else 0
                # Detect outliers: very high or very low values
                if val > 5000 or (val < 0.001 and val != 0):
                    anomaly_score = 0.9
                elif val > 1000 or (val < 0.01 and val != 0):
                    anomaly_score = 0.7
                elif val > 100 or (val < 0.1 and val != 0):
                    anomaly_score = 0.4
            except (ValueError, TypeError):
                pass
        
        # Trace anomalies (slow spans)
        if kind == "trace":
            spans = event.get("spans", []) or data.get("spans", []) or []
            max_duration = max((s.get("duration_ms", 0) for s in spans), default=0)
            if max_duration > 10000:
                anomaly_score = 0.95
            elif max_duration > 5000:
                anomaly_score = 0.85
            elif max_duration > 2000:
                anomaly_score = 0.6
        
        # Error logs are always anomalous
        if kind == "log":
            level = (event.get("level", "") or data.get("level", "")).lower()
            if level == "error":
                anomaly_score = 0.95
            elif level == "warn":
                anomaly_score = 0.5
        
        return min(1.0, anomaly_score)

    @staticmethod
    def _score_event(event: Event) -> float:
        """Score an event for relevance to incidents.

        Higher scores = more relevant.

        Args:
            event: Event to score

        Returns:
            Relevance score 0.0-1.0
        """
        score = 0.2  # Lower base score for better discrimination
        kind = event.get("kind", "")
        data = event.get("data", {})

        # Deploy events are high signal (infrastructure changes)
        if kind == "deploy":
            score += 0.6

        # Error logs are very high signal
        if kind == "log":
            level = (event.get("level", "") or data.get("level", "")).lower()
            if level == "error":
                score += 0.6
            elif level == "warn":
                score += 0.2

        # High metrics values are concerning
        if kind == "metric":
            try:
                value = float(event.get("value") or data.get("value", 0))
                if value > 5000 or (value < 0.0001 and value != 0):
                    score += 0.5
                elif value > 1000 or (value < 0.001 and value != 0):
                    score += 0.3
                elif value > 100 or (value < 0.01 and value != 0):
                    score += 0.15
            except (ValueError, TypeError):
                pass

        # Slow traces are concerning
        if kind == "trace":
            spans = event.get("spans", []) or data.get("spans", []) or []
            max_duration = max((s.get("duration_ms", 0) for s in spans), default=0)
            if max_duration > 5000:
                score += 0.5
            elif max_duration > 2000:
                score += 0.3
            else:
                score += 0.1

        # Incident signals themselves are highest value
        if kind == "incident_signal":
            score += 0.7

        # Remediation events show resolution
        if kind == "remediation":
            score += 0.4

        # Cap at 1.0
        return min(score, 1.0)


class RemediationRanker:
    """Ranks suggested remediations by historical success."""

    @staticmethod
    def rank_remediations(
        candidates: list[dict[str, Any]],
        successful_history: list[dict[str, Any]] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Rank remediation suggestions by historical success.

        Args:
            candidates: Candidate remediations
            successful_history: Past successful remediations
            limit: Max suggestions to return

        Returns:
            Top-ranked suggestions
        """
        if not candidates:
            return []

        successful_history = successful_history or []

        # Count successes by action type
        success_counts: dict[str, int] = {}
        for rem in successful_history:
            action = rem.get("action", "")
            success_counts[action] = success_counts.get(action, 0) + 1

        # Score each candidate
        scored = []
        for cand in candidates:
            score = RemediationRanker._score_remediation(cand, success_counts)
            scored.append((cand, score))

        # Sort by score descending
        scored.sort(key=lambda x: -x[1])

        # Return top N
        return [rem for rem, _ in scored[:limit]]

    @staticmethod
    def _score_remediation(
        remediation: dict[str, Any],
        success_counts: dict[str, int],
    ) -> float:
        """Score a remediation candidate.

        Args:
            remediation: Remediation to score
            success_counts: Counter of successful actions

        Returns:
            Score 0.0-1.0
        """
        score = 0.5

        action = remediation.get("action", "").lower()

        # Check historical success rate
        if action in success_counts:
            successes = success_counts.get(action, 0)
            # More successes = higher confidence
            score += min(successes / 10.0, 0.3)

        # Rollback is a safe, proven action
        if "rollback" in action:
            score += 0.1

        # Record existing confidence
        if "confidence" in remediation:
            score = remediation["confidence"]

        return min(score, 1.0)
