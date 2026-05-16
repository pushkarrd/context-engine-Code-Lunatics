"""Event handlers for different event kinds."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    import networkx as nx
except Exception:  # pragma: no cover - optional dependency
    nx = None


def _parse_ts(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _event_node_id(event: dict[str, Any], suffix: str | None = None) -> str:
    if event.get("id"):
        return str(event["id"])
    ts = event.get("ts")
    ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
    svc = event.get("service", "unknown")
    kind = event.get("kind", "event")
    if suffix:
        return f"{kind}:{svc}:{ts_str}:{suffix}"
    return f"{kind}:{svc}:{ts_str}"


def _add_node(graph_builder: Any, node_id: str, **attrs: Any) -> None:
    if hasattr(graph_builder, "graph") and nx is not None:
        graph_builder.graph.add_node(node_id, **attrs)


def _add_edge(graph_builder: Any, source: str, target: str, evidence: str, confidence: float) -> None:
    if hasattr(graph_builder, "add_edge"):
        graph_builder.add_edge(source, target, evidence=evidence, confidence=confidence)


def _store(event: dict[str, Any], event_store: Any) -> None:
    if event.get("_persisted"):
        return
    if hasattr(event_store, "store_event"):
        event_store.store_event(event)


def handle_deploy(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle deploy event — mark as potential incident trigger."""
    _store(event, event_store)

    node_id = _event_node_id(event)
    _add_node(
        graph_builder,
        node_id,
        kind="deploy",
        service=event.get("service"),
        ts=_parse_ts(event.get("ts")),
        data=dict(event),
        trigger_candidate=True,
    )


def handle_log(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle log event — add error nodes and trace links when applicable."""
    _store(event, event_store)

    level = str(event.get("level", "")).lower()
    if level in {"error", "critical"}:
        node_id = _event_node_id(event)
        _add_node(
            graph_builder,
            node_id,
            kind="log",
            level=level,
            service=event.get("service"),
            ts=_parse_ts(event.get("ts")),
            data=dict(event),
        )

    trace_id = event.get("trace_id")
    if trace_id:
        trace_node = f"trace:{trace_id}"
        log_node = _event_node_id(event, suffix="log")
        _add_node(
            graph_builder,
            log_node,
            kind="log",
            level=level,
            service=event.get("service"),
            ts=_parse_ts(event.get("ts")),
            data=dict(event),
        )
        _add_edge(graph_builder, trace_node, log_node, "trace linked to log", 0.6)


def handle_metric(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle metric event — detect anomalies and add causal edges."""
    _store(event, event_store)

    name = str(event.get("name", ""))
    value = event.get("value")
    if name == "latency_p99_ms" and isinstance(value, (int, float)) and value > 2000:
        node_id = _event_node_id(event, suffix="latency_spike")
        _add_node(
            graph_builder,
            node_id,
            kind="metric",
            metric=name,
            spike=True,
            service=event.get("service"),
            ts=_parse_ts(event.get("ts")),
            data=dict(event),
        )
        svc = event.get("service", "unknown")
        svc_node = f"svc:{svc}"
        _add_edge(graph_builder, svc_node, node_id, "latency_p99_ms spike", 0.7)


def handle_trace(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle trace event — create service dependency edges."""
    _store(event, event_store)

    spans = event.get("spans", []) or []
    for i in range(len(spans) - 1):
        current = spans[i]
        next_span = spans[i + 1]
        src = f"svc:{current.get('svc', 'unknown')}"
        dst = f"svc:{next_span.get('svc', 'unknown')}"
        dur = current.get("dur_ms", 0)
        evidence = f"RPC call: {current.get('svc')} -> {next_span.get('svc')} ({dur}ms)"
        confidence = 0.7 if isinstance(dur, (int, float)) and dur > 1000 else 0.5
        _add_edge(graph_builder, src, dst, evidence, confidence)

        if isinstance(dur, (int, float)) and dur > 1000:
            latency_node = f"latency:{current.get('svc', 'unknown')}:{event.get('trace_id', '')}"
            _add_node(
                graph_builder,
                latency_node,
                kind="trace_latency",
                duration_ms=dur,
                ts=_parse_ts(event.get("ts")),
                data=dict(event),
            )
            _add_edge(graph_builder, src, latency_node, "slow span", 0.6)


def handle_topology(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle topology change event — register renames and merge nodes."""
    _store(event, event_store)

    change_type = str(event.get("change", "")).lower()
    if change_type != "rename":
        return

    from_name = event.get("from_", "") or event.get("from", "")
    to_name = event.get("to", "")
    ts = _parse_ts(event.get("ts"))
    if not from_name or not to_name:
        return

    alias_registry.register_rename(from_name, to_name, ts)

    if hasattr(graph_builder, "graph") and nx is not None:
        canonical = alias_registry.resolve(from_name)
        mapping: dict[str, str] = {}
        if graph_builder.graph.has_node(from_name):
            mapping[from_name] = canonical
        if graph_builder.graph.has_node(to_name):
            mapping[to_name] = canonical
        if mapping:
            nx.relabel_nodes(graph_builder.graph, mapping, copy=False)


def handle_incident_signal(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle incident signal — start tracking incident metadata."""
    _store(event, event_store)

    incident_id = event.get("incident_id")
    if not incident_id:
        return

    _add_node(
        graph_builder,
        incident_id,
        kind="incident_signal",
        service=event.get("service"),
        ts=_parse_ts(event.get("ts")),
        data=dict(event),
    )

    try:
        service = event.get("service", "")
        ts = _parse_ts(event.get("ts"))
        if service and hasattr(alias_registry, "get_all_aliases"):
            service = alias_registry.get_all_aliases(service)

        related_events = []
        if hasattr(event_store, "query_time_window") and service:
            related_events = event_store.query_time_window(service, ts, window_minutes=10)

        if hasattr(incident_memory, "remember_incident"):
            incident_memory.remember_incident(incident_id, event, related_events)
    except Exception:
        pass

    if hasattr(incident_memory, "_incidents"):
        incident_memory._incidents.setdefault(incident_id, {})
        incident_memory._incidents[incident_id].update({
            "signal_ts": _parse_ts(event.get("ts")),
            "trigger": event.get("trigger", ""),
        })


def handle_remediation(
    event: dict[str, Any],
    event_store: Any,
    graph_builder: Any,
    alias_registry: Any,
    incident_memory: Any,
) -> None:
    """Handle remediation event — record remediation outcomes."""
    _store(event, event_store)

    incident_id = event.get("incident_id")
    if not incident_id:
        return

    if hasattr(incident_memory, "record_remediation"):
        incident_memory.record_remediation(incident_id, event)

    outcome = str(event.get("outcome", "")).lower()
    if outcome in {"resolved", "success"} and hasattr(incident_memory, "_incidents"):
        incident_memory._incidents.setdefault(incident_id, {})
        incident_memory._incidents[incident_id]["outcome"] = outcome