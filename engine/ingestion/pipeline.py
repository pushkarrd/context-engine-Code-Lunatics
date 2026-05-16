"""Event ingestion pipeline — parses, validates, routes events."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from engine.ingestion import handlers

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


class IngestionPipeline:
    """Validates and routes telemetry events to appropriate handlers."""

    def __init__(self, event_store: Any, graph_builder: Any, alias_registry: Any, incident_memory: Any) -> None:
        """Initialize pipeline with dependencies.

        Args:
            event_store: DuckDB event storage
            graph_builder: Causal graph builder/adapter
            alias_registry: Topology drift handler
            incident_memory: Incident memory manager
        """
        self.event_store = event_store
        self.graph_builder = graph_builder
        self.alias_registry = alias_registry
        self.incident_memory = incident_memory

        self._handlers = {
            "deploy": handlers.handle_deploy,
            "log": handlers.handle_log,
            "metric": handlers.handle_metric,
            "trace": handlers.handle_trace,
            "topology": handlers.handle_topology,
            "incident_signal": handlers.handle_incident_signal,
            "remediation": handlers.handle_remediation,
        }

    def consume(self, event: dict[str, Any]) -> None:
        """Consume a single event.

        Validates required fields and routes to the correct handler.

        Args:
            event: Event dict.
        """
        if not self._validate(event):
            return

        event["ts"] = _parse_ts(event.get("ts"))
        handler = self._handlers.get(event.get("kind"))

        if not handler:
            logger.warning("Unknown event kind: %s", event.get("kind"))
            return

        handler(event, self.event_store, self.graph_builder, self.alias_registry, self.incident_memory)

    def consume_batch(self, events: list[dict[str, Any]]) -> None:
        """Consume a batch of events efficiently.

        Uses batch insert for DuckDB and then routes each event to its handler.

        Args:
            events: List of events to ingest.
        """
        if not events:
            return

        valid: list[dict[str, Any]] = []
        for event in events:
            if not self._validate(event):
                continue
            event["ts"] = _parse_ts(event.get("ts"))
            event["_persisted"] = True
            valid.append(event)

        if not valid:
            return

        if hasattr(self.event_store, "store_events_batch"):
            self.event_store.store_events_batch(valid)

        for event in valid:
            handler = self._handlers.get(event.get("kind"))
            if not handler:
                logger.warning("Unknown event kind: %s", event.get("kind"))
                continue
            handler(event, self.event_store, self.graph_builder, self.alias_registry, self.incident_memory)

    def _validate(self, event: dict[str, Any]) -> bool:
        """Validate that required fields are present.

        Args:
            event: Event to validate.

        Returns:
            True if valid, False otherwise.
        """
        kind = event.get("kind")
        if not kind or not event.get("ts"):
            return False

        if kind == "deploy":
            return bool(event.get("service"))
        if kind == "log":
            return bool(event.get("service") and event.get("msg"))
        if kind == "metric":
            return bool(event.get("service") and event.get("name"))
        if kind == "trace":
            return bool(event.get("trace_id") and event.get("spans"))
        if kind == "topology":
            return bool(event.get("change") and event.get("from_") and event.get("to"))
        if kind == "incident_signal":
            return bool(event.get("incident_id"))
        if kind == "remediation":
            return bool(event.get("incident_id") and event.get("action") and event.get("target"))

        return True

    def ingest_events(self, events: list[dict[str, Any]]) -> None:
        """Backward-compatible entry point for existing callers."""
        self.consume_batch(events)
