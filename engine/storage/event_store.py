"""DuckDB-backed event store for infrastructure telemetry."""
from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb

from schema import Event


def _parse_ts(ts: str | datetime | None) -> datetime:
    """Normalize timestamps to timezone-aware UTC datetimes."""
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    """Format timestamps as ISO-8601 UTC strings."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventStore:
    """DuckDB event store with a small connection pool for concurrency."""

    def __init__(self, db_path: str | None = None, pool_size: int = 4) -> None:
        """Initialize DuckDB and schema.

        Args:
            db_path: Path to DuckDB file (defaults to DUCKDB_PATH env or ./data/events.db).
            pool_size: Max number of pooled connections for concurrent access.
        """
        self.db_path = db_path or os.environ.get("DUCKDB_PATH", "./data/events.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._pool_size = max(1, pool_size)
        self._pool: queue.Queue[duckdb.DuckDBPyConnection] = queue.Queue(
            maxsize=self._pool_size
        )
        self._pool_lock = threading.Lock()
        self._created = 0
        self._closed = False

        # Initialize schema using a dedicated connection, then keep it in the pool.
        conn = duckdb.connect(self.db_path)
        self._init_schema(conn)
        self._pool.put(conn)
        self._created = 1

    def _init_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create tables if they don't exist."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id VARCHAR PRIMARY KEY,
                ts TIMESTAMP,
                kind VARCHAR,
                service VARCHAR,
                data JSON,
                ingested_at TIMESTAMP DEFAULT now()
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_service ON events(service)")

    @contextmanager
    def _get_conn(self) -> Iterable[duckdb.DuckDBPyConnection]:
        """Borrow a connection from the pool and return it safely."""
        if self._closed:
            raise RuntimeError("EventStore is closed")

        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            with self._pool_lock:
                if self._created < self._pool_size:
                    conn = duckdb.connect(self.db_path)
                    self._created += 1
                else:
                    conn = self._pool.get()

        try:
            yield conn
        finally:
            if self._closed:
                conn.close()
            else:
                self._pool.put(conn)

    def store_event(self, event: dict[str, Any]) -> None:
        """Store a single event in DuckDB.

        Generates an id if missing and stores the full event JSON in the data column.

        Args:
            event: Event dict to store.
        """
        event_id = str(event.get("id") or uuid.uuid4())
        ts = _parse_ts(event.get("ts"))
        payload = dict(event)
        payload["id"] = event_id
        payload["ts"] = _iso(ts)

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO events (id, ts, kind, service, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    event_id,
                    ts,
                    event.get("kind"),
                    event.get("service"),
                    json.dumps(payload, default=str),
                ],
            )

    def store_events_batch(self, events: list[dict[str, Any]]) -> None:
        """Bulk insert events for high-throughput ingestion.

        Args:
            events: List of event dicts to insert.
        """
        if not events:
            return

        records: list[tuple[str, datetime, str | None, str | None, str]] = []
        for event in events:
            event_id = str(event.get("id") or uuid.uuid4())
            ts = _parse_ts(event.get("ts"))
            payload = dict(event)
            payload["id"] = event_id
            payload["ts"] = _iso(ts)
            records.append(
                (
                    event_id,
                    ts,
                    event.get("kind"),
                    event.get("service"),
                    json.dumps(payload, default=str),
                )
            )

        def _batch_insert() -> None:
            with self._get_conn() as conn:
                conn.executemany(
                    """
                    INSERT INTO events (id, ts, kind, service, data)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    records,
                )

        try:
            _batch_insert()
        except RuntimeError as exc:
            message = str(exc).lower()
            if "interrupted" not in message:
                raise
            logger.warning("DuckDB batch insert interrupted; retrying once")
            try:
                _batch_insert()
            except RuntimeError as retry_exc:
                logger.warning("DuckDB batch insert retry failed: %s", retry_exc)
                for event in events:
                    self.store_event(event)

    def query_time_window(
        self,
        service: str | Sequence[str],
        ts: datetime,
        window_minutes: int = 10,
    ) -> list[dict[str, Any]]:
        """Return events for a service within ±window_minutes of ts.

        Args:
            service: Service name or list of alias names to include.
            ts: Center timestamp for the query window.
            window_minutes: Window size in minutes around ts.

        Returns:
            List of event dicts.
        """
        services = [service] if isinstance(service, str) else list(service)
        if not services:
            return []

        ts_center = _parse_ts(ts)
        ts_min = ts_center - timedelta(minutes=window_minutes)
        ts_max = ts_center + timedelta(minutes=window_minutes)

        placeholders = ", ".join(["?"] * len(services))
        query = f"""
            SELECT id, ts, kind, service, data
            FROM events
            WHERE service IN ({placeholders}) AND ts BETWEEN ? AND ?
            ORDER BY ts ASC
        """

        with self._get_conn() as conn:
            rows = conn.execute(query, [*services, ts_min, ts_max]).fetchall()

        return self._rows_to_events(rows)

    def get_events_by_incident(self, incident_id: str) -> list[dict[str, Any]]:
        """Return all events associated with an incident_id.

        Args:
            incident_id: Incident ID to match.

        Returns:
            List of event dicts.
        """
        if not incident_id:
            return []

        query = (
            "SELECT id, ts, kind, service, data FROM events "
            "WHERE json_extract_string(data, '$.incident_id') = ? "
            "ORDER BY ts ASC"
        )

        with self._get_conn() as conn:
            rows = conn.execute(query, [incident_id]).fetchall()

        return self._rows_to_events(rows)

    def get_recent_deploys(self, service: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return most recent deploy events for a service.

        Args:
            service: Service name.
            limit: Maximum number of deploys to return.

        Returns:
            List of deploy event dicts, newest first.
        """
        if not service:
            return []

        query = (
            "SELECT id, ts, kind, service, data FROM events "
            "WHERE kind = 'deploy' AND service = ? "
            "ORDER BY ts DESC LIMIT ?"
        )

        with self._get_conn() as conn:
            rows = conn.execute(query, [service, limit]).fetchall()

        return self._rows_to_events(rows)

    def query_window(
        self,
        service: str | None = None,
        ts_min: datetime | None = None,
        ts_max: datetime | None = None,
        kind: str | None = None,
        limit: int = 1000,
    ) -> list[Event]:
        """Query events in a time window with optional filters.

        Args:
            service: Optional service name filter.
            ts_min: Minimum timestamp (inclusive).
            ts_max: Maximum timestamp (inclusive).
            kind: Optional event kind filter.
            limit: Max results.

        Returns:
            List of events matching criteria.
        """
        whereparts: list[str] = []
        params: list[Any] = []

        if service:
            whereparts.append("service = ?")
            params.append(service)

        if ts_min:
            whereparts.append("ts >= ?")
            params.append(_parse_ts(ts_min))

        if ts_max:
            whereparts.append("ts <= ?")
            params.append(_parse_ts(ts_max))

        if kind:
            whereparts.append("kind = ?")
            params.append(kind)

        where_clause = " AND ".join(whereparts) if whereparts else "1=1"
        query = (
            "SELECT id, ts, kind, service, data FROM events "
            f"WHERE {where_clause} "
            "ORDER BY ts DESC LIMIT ?"
        )
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return self._rows_to_events(rows)

    def get_events_for_incident(
        self,
        incident_id: str,
        window_minutes: int = 10,
    ) -> list[Event]:
        """Get events around the incident signal timestamp.

        Args:
            incident_id: Incident ID to find.
            window_minutes: Minutes before/after the signal to include.

        Returns:
            List of related events.
        """
        signal_query = (
            "SELECT id, ts, kind, service, data FROM events "
            "WHERE kind = 'incident_signal' AND "
            "json_extract_string(data, '$.incident_id') = ? "
            "ORDER BY ts DESC LIMIT 1"
        )

        with self._get_conn() as conn:
            signal_rows = conn.execute(signal_query, [incident_id]).fetchall()

        if not signal_rows:
            return self.get_events_by_incident(incident_id)

        signal_event = self._rows_to_events(signal_rows)[0]
        service = signal_event.get("service")
        if not service:
            return self.get_events_by_incident(incident_id)

        signal_ts = _parse_ts(signal_event.get("ts"))
        return self.query_time_window(service, signal_ts, window_minutes=window_minutes)

    def get_by_trace_id(self, trace_id: str) -> list[Event]:
        """Get all events with a given trace_id.

        Args:
            trace_id: The trace ID to search for.

        Returns:
            All events in the trace.
        """
        if not trace_id:
            return []

        query = (
            "SELECT id, ts, kind, service, data FROM events "
            "WHERE json_extract_string(data, '$.trace_id') = ? "
            "ORDER BY ts ASC"
        )

        with self._get_conn() as conn:
            rows = conn.execute(query, [trace_id]).fetchall()

        return self._rows_to_events(rows)

    def count_events(self) -> int:
        """Return the total number of stored events."""
        with self._get_conn() as conn:
            result = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(result[0]) if result else 0

    def close(self) -> None:
        """Close all pooled connections."""
        if self._closed:
            return

        self._closed = True
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            conn.close()

    def _rows_to_events(self, rows: list[tuple[Any, ...]]) -> list[Event]:
        """Convert DuckDB rows into event dicts."""
        events: list[Event] = []
        for row in rows:
            event_id, ts, kind, service, data_raw = row
            payload: dict[str, Any] = {}

            if isinstance(data_raw, dict):
                payload = dict(data_raw)
            elif isinstance(data_raw, str):
                try:
                    payload = json.loads(data_raw)
                except json.JSONDecodeError:
                    payload = {}

            if event_id and not payload.get("id"):
                payload["id"] = event_id
            if ts:
                payload["ts"] = _iso(_parse_ts(ts))
            if kind and not payload.get("kind"):
                payload["kind"] = kind
            if service and not payload.get("service"):
                payload["service"] = service

            events.append(payload)

        return events

    def __del__(self) -> None:
        """Ensure connections are closed on deletion."""
        self.close()
