"""Causal graph builder and traversal."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

import networkx as nx


def _parse_ts(ts: str | datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class _Edge:
    cause_id: str
    effect_id: str
    evidence: str
    confidence: float


class CausalGraph:
    """Directed graph of causal relationships between events.

    Example:
        >>> g = CausalGraph()
        >>> g.add_event_node("e1", {"kind": "deploy", "service": "svc", "ts": "2026-05-01T00:00:00Z"})
        >>> g.add_event_node("e2", {"kind": "metric", "service": "svc", "name": "latency_p99_ms", "ts": "2026-05-01T00:04:00Z"})
        >>> g.add_causal_edge("e1", "e2", "deploy before spike", 0.7)
    """

    def __init__(self) -> None:
        """Initialize a thread-safe NetworkX DiGraph."""
        self.graph: nx.DiGraph = nx.DiGraph()
        self._lock = RLock()

    def add_event_node(self, event_id: str, event: dict[str, Any]) -> None:
        """Add a node for this event.

        Args:
            event_id: Unique event identifier.
            event: Event dict containing kind, service, ts, and data fields.
        """
        if not event_id:
            return
        with self._lock:
            self.graph.add_node(
                event_id,
                kind=event.get("kind"),
                service=event.get("service"),
                ts=_parse_ts(event.get("ts")),
                data=dict(event),
            )

    def add_causal_edge(
        self,
        cause_id: str,
        effect_id: str,
        evidence: str,
        confidence: float,
    ) -> None:
        """Add directed edge from cause to effect.

        Args:
            cause_id: Event ID of the cause.
            effect_id: Event ID of the effect.
            evidence: Rationale for the relationship.
            confidence: Confidence score between 0.0 and 1.0.
        """
        if not cause_id or not effect_id:
            return
        with self._lock:
            self.graph.add_edge(
                cause_id,
                effect_id,
                evidence=evidence,
                confidence=float(confidence),
                ts=datetime.now(timezone.utc),
            )

    def infer_edges(self) -> None:
        """Infer causal edges using advanced heuristic rules with adaptive timeouts and confidence boosting."""
        with self._lock:
            nodes = list(self.graph.nodes(data=True))

        if not nodes:
            return

        deploys = [n for n in nodes if n[1].get("kind") == "deploy"]
        metrics = [n for n in nodes if n[1].get("kind") == "metric"]
        logs = [n for n in nodes if n[1].get("kind") == "log"]
        traces = [n for n in nodes if n[1].get("kind") == "trace"]
        incidents = [n for n in nodes if n[1].get("kind") == "incident_signal"]

        # === ENHANCED RULE 1: deploy -> latency spike ===
        # Adaptive: up to 15 min, higher confidence if within 5 min
        for d_id, d in deploys:
            d_ts = d.get("ts")
            for m_id, m in metrics:
                m_data = m.get("data", {})
                if not _is_latency_spike(m_data):
                    continue
                m_ts = m.get("ts")
                if _is_before_within(d_ts, m_ts, 15):
                    delta_min = (m_ts - d_ts).total_seconds() / 60.0
                    # Higher confidence if within 5 min window
                    confidence = 0.85 if delta_min <= 5 else 0.72
                    self.add_causal_edge(d_id, m_id, f"deploy before latency spike ({delta_min:.1f} min)", confidence)

        # === ENHANCED RULE 2: latency spike -> error log ===
        # Adaptive: up to 8 min, confidence varies with proximity
        for m_id, m in metrics:
            m_data = m.get("data", {})
            if not _is_latency_spike(m_data):
                continue
            m_ts = m.get("ts")
            for l_id, l in logs:
                l_data = l.get("data", {})
                if not _is_error_log(l_data):
                    continue
                l_ts = l.get("ts")
                if _is_before_within(m_ts, l_ts, 8):
                    delta_min = (l_ts - m_ts).total_seconds() / 60.0
                    # Higher confidence if immediate
                    confidence = 0.92 if delta_min <= 2 else 0.80
                    self.add_causal_edge(m_id, l_id, f"latency spike before error log ({delta_min:.1f} min)", confidence)

        # === ENHANCED RULE 3: error log -> incident_signal ===
        # Adaptive: up to 15 min, confidence varies
        for l_id, l in logs:
            l_data = l.get("data", {})
            if not _is_error_log(l_data):
                continue
            l_ts = l.get("ts")
            for i_id, inc in incidents:
                i_ts = inc.get("ts")
                if _is_before_within(l_ts, i_ts, 15):
                    delta_min = (i_ts - l_ts).total_seconds() / 60.0
                    confidence = 0.95 if delta_min <= 3 else 0.85
                    self.add_causal_edge(l_id, i_id, f"error log before incident signal ({delta_min:.1f} min)", confidence)

        # === NEW RULE 4: trace anomaly -> incident ===
        # Slow traces are often precursors to incidents
        for t_id, t in traces:
            t_data = t.get("data", {})
            spans = t_data.get("spans", []) or t.get("spans", []) or []
            if not any(s.get("duration_ms", 0) > 3000 for s in spans):
                continue
            max_duration = max((s.get("duration_ms", 0) for s in spans), default=0)
            t_ts = t.get("ts")
            for i_id, inc in incidents:
                i_ts = inc.get("ts")
                if _is_before_within(t_ts, i_ts, 12):
                    delta_min = (i_ts - t_ts).total_seconds() / 60.0
                    # Confidence based on how severe the slow trace is
                    severity_factor = min(1.0, max_duration / 5000.0)
                    confidence = 0.60 + (severity_factor * 0.25)
                    self.add_causal_edge(t_id, i_id, f"slow trace ({max_duration:.0f}ms) before incident", confidence)

        # === NEW RULE 5: deploy -> error log ===
        # Direct path: some deploys cause errors immediately
        for d_id, d in deploys:
            d_ts = d.get("ts")
            for l_id, l in logs:
                l_data = l.get("data", {})
                if not _is_error_log(l_data):
                    continue
                l_ts = l.get("ts")
                if _is_before_within(d_ts, l_ts, 6):
                    delta_min = (l_ts - d_ts).total_seconds() / 60.0
                    confidence = 0.78 if delta_min <= 2 else 0.65
                    self.add_causal_edge(d_id, l_id, f"deploy directly before error log ({delta_min:.1f} min)", confidence)

        # === NEW RULE 6: deploy -> incident (direct) ===
        # Some problematic deploys cascade to incidents quickly
        for d_id, d in deploys:
            d_ts = d.get("ts")
            for i_id, inc in incidents:
                i_ts = inc.get("ts")
                if _is_before_within(d_ts, i_ts, 10):
                    delta_min = (i_ts - d_ts).total_seconds() / 60.0
                    if delta_min <= 3:
                        confidence = 0.70
                        self.add_causal_edge(d_id, i_id, f"deploy directly precedes incident ({delta_min:.1f} min)", confidence)

    def get_causal_chain(self, incident_id: str, max_depth: int = 5) -> list[dict[str, Any]]:
        """Traverse backwards from incident and return ordered causal edges.

        Args:
            incident_id: Incident signal event id.
            max_depth: Maximum depth to traverse.

        Returns:
            List of causal edges in root-cause to effect order.
        """
        if not incident_id:
            return []

        self.infer_edges()
        with self._lock:
            if incident_id not in self.graph:
                return []

            edges: list[_Edge] = []
            visited = set()
            queue: list[tuple[str, int]] = [(incident_id, 0)]

            while queue:
                node, depth = queue.pop(0)
                if depth >= max_depth or node in visited:
                    continue
                visited.add(node)

                for pred in self.graph.predecessors(node):
                    edge_data = self.graph.get_edge_data(pred, node) or {}
                    confidence = float(edge_data.get("confidence", 0.0))
                    # Use 0.35 threshold for better recall
                    if confidence < 0.35:
                        continue
                    edges.append(
                        _Edge(
                            cause_id=pred,
                            effect_id=node,
                            evidence=edge_data.get("evidence", ""),
                            confidence=confidence,
                        )
                    )
                    queue.append((pred, depth + 1))

        edges.sort(key=lambda e: _edge_sort_key(self.graph, e))
        return [
            {
                "cause_id": e.cause_id,
                "effect_id": e.effect_id,
                "evidence": e.evidence,
                "confidence": e.confidence,
            }
            for e in edges
        ]

    def get_related_events(self, service: str, ts: datetime, window_minutes: int = 10) -> list[str]:
        """Return event IDs within the time window connected to a service.

        Args:
            service: Service name.
            ts: Center time.
            window_minutes: Window size in minutes.

        Returns:
            List of event IDs.
        """
        if not service:
            return []

        ts_center = _parse_ts(ts)
        ts_min = ts_center - timedelta(minutes=window_minutes)
        ts_max = ts_center + timedelta(minutes=window_minutes)

        with self._lock:
            nodes = [
                n for n, data in self.graph.nodes(data=True)
                if data.get("service") == service and ts_min <= data.get("ts") <= ts_max
            ]

            related = set(nodes)
            for node in nodes:
                related.update(self.graph.predecessors(node))
                related.update(self.graph.successors(node))

        return list(related)

    def merge_service_nodes(self, old_service: str, new_service: str) -> None:
        """Rewire edges from old_service to new_service canonical.

        Args:
            old_service: Old service name.
            new_service: New canonical service name.
        """
        if not old_service or not new_service or old_service == new_service:
            return

        with self._lock:
            nodes = [
                n for n, data in self.graph.nodes(data=True)
                if data.get("service") == old_service
            ]
            for node in nodes:
                self.graph.nodes[node]["service"] = new_service


def _within_minutes(a: Any, b: Any, minutes: int) -> bool:
    if a is None or b is None:
        return False
    return abs(_parse_ts(a) - _parse_ts(b)) <= timedelta(minutes=minutes)


def _is_before_within(a: Any, b: Any, minutes: int) -> bool:
    if a is None or b is None:
        return False
    delta = _parse_ts(b) - _parse_ts(a)
    return timedelta(0) <= delta <= timedelta(minutes=minutes)


def _is_latency_spike(data: dict[str, Any]) -> bool:
    name = str(data.get("name", "")).lower()
    value = data.get("value")
    return "latency" in name and isinstance(value, (int, float)) and value > 2000


def _is_error_log(data: dict[str, Any]) -> bool:
    level = str(data.get("level", "")).lower()
    return level == "error"


def _edge_sort_key(graph: nx.DiGraph, edge: _Edge) -> datetime:
    cause_ts = graph.nodes.get(edge.cause_id, {}).get("ts")
    return _parse_ts(cause_ts)
