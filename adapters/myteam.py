"""Team submission adapter for P-02 Persistent Context Engine."""
from __future__ import annotations

from adapter import Adapter
from engine.core import MemorySubstrate
from schema import Context, Event, IncidentSignal


class Engine(Adapter):
    """Thin adapter that delegates to MemorySubstrate."""

    def __init__(self) -> None:
        """Initialise the memory substrate."""
        self.store = MemorySubstrate()

    def ingest(self, events) -> None:
        """Consume a stream of telemetry events.

        Called with an iterable of Event dicts.
        Must handle 1000+ events/sec.
        """
        events_list = list(events)
        if events_list:
            self.store.consume_batch(events_list)

    def reconstruct_context(self, signal: IncidentSignal, mode: str = "fast") -> Context:
        """Reconstruct operational context for an incident signal.

        fast mode: p95 ≤ 2 seconds
        deep mode: p95 ≤ 6 seconds
        """
        return self.store.reconstruct(dict(signal), mode=mode)

    def close(self) -> None:
        """Shutdown gracefully."""
        self.store.shutdown()
