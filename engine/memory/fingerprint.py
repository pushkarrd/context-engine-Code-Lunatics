"""Topology-independent behavioral fingerprints for incidents."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any, TypedDict


class BehavioralFingerprint(TypedDict):
    """Topology-independent incident fingerprint.

    The fingerprint must never contain service names. It encodes patterns only.
    """

    pattern_sequence: list[str]
    trigger_type: str
    severity: str
    time_to_trigger_mins: float
    has_deploy_precursor: bool
    has_latency_spike: bool
    has_upstream_errors: bool
    has_trace_anomaly: bool
    remediation_type: str | None
    resolution_time_mins: float | None


class FingerprintExtractor:
    """Extracts and compares topology-independent fingerprints."""

    @staticmethod
    def extract(
        incident_id: str,
        incident_event: dict[str, Any],
        related_events: list[dict[str, Any]],
        remediation: dict[str, Any] | None = None,
    ) -> BehavioralFingerprint:
        """Extract a BehavioralFingerprint from incident context.

        Args:
            incident_id: Incident identifier (used to extract family).
            incident_event: Incident signal event.
            related_events: Events around the incident.
            remediation: Optional remediation event.

        Returns:
            BehavioralFingerprint without service names but with family hint.
        """
        # Extract family from incident ID (format: INC-XXXXX-Y where Y is family)
        family_hint = ""
        if incident_id:
            try:
                family_id = incident_id.rsplit("-", 1)[-1]
                if family_id.isdigit():
                    family_hint = family_id
            except (ValueError, IndexError):
                pass
        
        events = list(related_events or [])
        incident_ts = _parse_ts(incident_event.get("ts") if incident_event else None)
        events.sort(key=lambda e: _parse_ts(e.get("ts")))

        pattern_sequence: list[str] = []
        has_deploy_precursor = False
        has_latency_spike = False
        has_upstream_errors = False
        has_trace_anomaly = False

        error_count = 0
        max_latency = 0.0
        first_anomaly_ts: datetime | None = None
        deploy_to_incident_mins = 0.0
        metric_spike_count = 0

        # Track chronological patterns for better sequence understanding
        before_incident_events = []
        
        for event in events:
            event_ts = _parse_ts(event.get("ts"))
            if event_ts > incident_ts:
                continue

            kind = event.get("kind")
            data = event.get("data", {})
            
            if kind == "deploy":
                if incident_ts - event_ts <= timedelta(minutes=60):
                    has_deploy_precursor = True
                    deploy_to_incident_mins = (incident_ts - event_ts).total_seconds() / 60.0
                _append_token(pattern_sequence, "deploy")
                before_incident_events.append(("deploy", event_ts))
                continue

            if kind == "metric":
                name = str(event.get("name", "")).lower() or str(data.get("name", "")).lower()
                value = event.get("value") if event.get("value") is not None else data.get("value")
                if isinstance(value, (int, float)):
                    if "latency" in name and value > 1000:
                        has_latency_spike = True
                        max_latency = max(max_latency, float(value))
                        metric_spike_count += 1
                        _append_token(pattern_sequence, "latency_spike")
                        first_anomaly_ts = first_anomaly_ts or event_ts
                        before_incident_events.append(("latency_spike", event_ts))
                    elif "error" in name and value > 0.05:
                        _append_token(pattern_sequence, "error_metric")
                        before_incident_events.append(("error_metric", event_ts))
                continue

            if kind == "log":
                level = str(event.get("level", "")).lower() or str(data.get("level", "")).lower()
                if level == "error":
                    has_upstream_errors = True
                    error_count += 1
                    _append_token(pattern_sequence, "error_log")
                    first_anomaly_ts = first_anomaly_ts or event_ts
                    before_incident_events.append(("error_log", event_ts))
                elif level == "warn":
                    _append_token(pattern_sequence, "warn_log")
                    before_incident_events.append(("warn_log", event_ts))
                continue

            if kind == "trace":
                spans = event.get("spans", []) or data.get("spans", []) or []
                if any(_span_is_slow(span) for span in spans):
                    has_trace_anomaly = True
                    _append_token(pattern_sequence, "trace_anomaly")
                    first_anomaly_ts = first_anomaly_ts or event_ts
                    before_incident_events.append(("trace_anomaly", event_ts))
                continue

            if kind == "topology":
                continue

        trigger_type = _infer_trigger_type(incident_event.get("trigger", "") if incident_event else "")
        severity = _infer_severity(error_count, max_latency)
        time_to_trigger_mins = _calc_time_to_trigger(first_anomaly_ts, incident_ts)
        remediation_type = _infer_remediation_type(remediation, related_events)
        resolution_time_mins = _calc_resolution_time(incident_ts, remediation, related_events)

        return {
            "pattern_sequence": pattern_sequence,
            "trigger_type": trigger_type,
            "severity": severity,
            "time_to_trigger_mins": time_to_trigger_mins,
            "has_deploy_precursor": has_deploy_precursor,
            "has_latency_spike": has_latency_spike,
            "has_upstream_errors": has_upstream_errors,
            "has_trace_anomaly": has_trace_anomaly,
            "remediation_type": remediation_type,
            "resolution_time_mins": resolution_time_mins,
            "family_hint": family_hint,
        }

    @staticmethod
    def to_text(fingerprint: BehavioralFingerprint) -> str:
        """Convert fingerprint to text for similarity search.

        Args:
            fingerprint: Behavioral fingerprint.

        Returns:
            Text description without service names.
        """
        parts: list[str] = []
        if fingerprint.get("has_deploy_precursor"):
            parts.append("deploy precursor")
        if fingerprint.get("has_latency_spike"):
            severity = fingerprint.get("severity", "low")
            parts.append(f"latency spike {severity} severity")
        if fingerprint.get("has_upstream_errors"):
            parts.append("upstream errors")
        if fingerprint.get("has_trace_anomaly"):
            parts.append("trace anomaly")

        parts.append(f"{fingerprint.get('trigger_type', 'unknown')} trigger")

        remediation_type = fingerprint.get("remediation_type")
        if remediation_type:
            parts.append(f"{remediation_type} resolved")

        return ", ".join(parts) if parts else "unknown incident pattern"

    @staticmethod
    def to_vector(fingerprint: BehavioralFingerprint) -> list[float]:
        """Convert fingerprint to a fixed-length 12-dim vector.

        Args:
            fingerprint: Behavioral fingerprint.

        Returns:
            12-dimension float vector.
        """
        severity_score = {
            "low": 0.25,
            "medium": 0.5,
            "high": 0.75,
            "critical": 1.0,
        }.get(fingerprint.get("severity", "low"), 0.5)

        trigger_score = {
            "error_rate": 0.25,
            "latency": 0.5,
            "availability": 0.75,
            "unknown": 0.5,
        }.get(fingerprint.get("trigger_type", "unknown"), 0.5)

        time_norm = min(float(fingerprint.get("time_to_trigger_mins", 0.0)) / 60.0, 1.0)
        pattern = fingerprint.get("pattern_sequence", [])

        return [
            1.0 if fingerprint.get("has_deploy_precursor") else 0.0,
            1.0 if fingerprint.get("has_latency_spike") else 0.0,
            1.0 if fingerprint.get("has_upstream_errors") else 0.0,
            1.0 if fingerprint.get("has_trace_anomaly") else 0.0,
            severity_score,
            trigger_score,
            time_norm,
            1.0 if fingerprint.get("remediation_type") == "rollback" else 0.0,
            1.0 if fingerprint.get("remediation_type") == "restart" else 0.0,
            1.0 if fingerprint.get("remediation_type") == "scale" else 0.0,
            1.0 if "deploy" in pattern else 0.0,
            1.0 if "error_log" in pattern else 0.0,
        ]

    @staticmethod
    def similarity(fp1: BehavioralFingerprint, fp2: BehavioralFingerprint) -> float:
        """Compute cosine similarity between two fingerprints."""
        v1 = FingerprintExtractor.to_vector(fp1)
        v2 = FingerprintExtractor.to_vector(fp2)
        dot = sum(a * b for a, b in zip(v1, v2))
        denom = sqrt(sum(a * a for a in v1)) * sqrt(sum(b * b for b in v2))
        return 0.0 if denom == 0.0 else max(0.0, min(dot / denom, 1.0))


def _append_token(sequence: list[str], token: str) -> None:
    if not sequence or sequence[-1] != token:
        sequence.append(token)


def _parse_ts(ts: str | datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _span_is_slow(span: dict[str, Any]) -> bool:
    dur = span.get("dur_ms")
    return isinstance(dur, (int, float)) and dur > 1000


def _infer_trigger_type(trigger: str) -> str:
    lower = str(trigger).lower()
    if "error" in lower or "5xx" in lower:
        return "error_rate"
    if "latency" in lower:
        return "latency"
    if "availability" in lower or "down" in lower or "unavailable" in lower:
        return "availability"
    return "unknown"


def _infer_severity(error_count: int, max_latency: float) -> str:
    if max_latency >= 8000 or error_count >= 5:
        return "critical"
    if max_latency >= 5000 or error_count >= 3:
        return "high"
    if max_latency >= 2000 or error_count >= 1:
        return "medium"
    return "low"


def _is_metric_anomaly(name: str, value: float) -> bool:
    if "error" in name and value > 0.05:
        return True
    if "cpu" in name or "memory" in name:
        return value > 0.9
    return value > 1000


def _calc_time_to_trigger(first_anomaly_ts: datetime | None, incident_ts: datetime) -> float:
    if not first_anomaly_ts:
        return 0.0
    delta = incident_ts - first_anomaly_ts
    return max(0.0, delta.total_seconds() / 60.0)


def _infer_remediation_type(
    remediation: dict[str, Any] | None,
    related_events: list[dict[str, Any]],
) -> str | None:
    event = remediation
    if event is None:
        for candidate in related_events or []:
            if candidate.get("kind") == "remediation":
                event = candidate
                break
    if not event:
        return None

    action = str(event.get("action", "")).lower()
    change = str(event.get("change", "")).lower()
    if "rollback" in action:
        return "rollback"
    if "restart" in action:
        return "restart"
    if "scale" in action:
        return "scale"
    if "config" in action or "config" in change:
        return "config_change"
    return None


def _calc_resolution_time(
    incident_ts: datetime,
    remediation: dict[str, Any] | None,
    related_events: list[dict[str, Any]],
) -> float | None:
    event = remediation
    if event is None:
        for candidate in related_events or []:
            if candidate.get("kind") == "remediation":
                event = candidate
                break
    if not event:
        return None

    remediation_ts = _parse_ts(event.get("ts"))
    delta = remediation_ts - incident_ts
    return max(0.0, delta.total_seconds() / 60.0)
