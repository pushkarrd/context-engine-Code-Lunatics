"""Core engine orchestrator — MemorySubstrate."""
from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class MemorySubstrate:
    """Coordinates all subsystems for the persistent context engine."""

    def __init__(self) -> None:
        """Initialize the engine and all subsystems in dependency order."""
        from engine.graph.alias_registry import AliasRegistry
        from engine.storage.event_store import EventStore
        from engine.graph.causal_graph import CausalGraph
        from engine.memory.fingerprint import FingerprintExtractor
        from engine.memory.vector_store import VectorStore
        from engine.memory.incident_memory import IncidentMemory
        from engine.ingestion.pipeline import IngestionPipeline
        from engine.llm.gemini_client import GeminiClient
        from engine.reconstruction.context_builder import ContextBuilder

        self._lock = RLock()

        self.alias_registry = AliasRegistry()
        self.event_store = EventStore()
        self.causal_graph = CausalGraph()
        self.fingerprint_extractor = FingerprintExtractor
        self.vector_store = VectorStore()
        self.incident_memory = IncidentMemory(
            self.vector_store,
            self.fingerprint_extractor,
            self.alias_registry,
        )
        self.pipeline = IngestionPipeline(
            self.event_store,
            self.causal_graph,
            self.alias_registry,
            self.incident_memory,
        )

        try:
            self.gemini_client = GeminiClient()
        except Exception as exc:  # pragma: no cover - depends on env
            self.gemini_client = None
            logger.warning("Gemini client unavailable: %s", exc)

        self.context_builder = ContextBuilder(
            self.event_store,
            self.causal_graph,
            self.incident_memory,
            self.alias_registry,
            self.gemini_client,
        )

        logger.info(
            "MemorySubstrate initialized (alias_registry=%s, event_store=%s, causal_graph=%s, "
            "vector_store=%s, incident_memory=%s, pipeline=%s, gemini=%s)",
            True,
            True,
            True,
            True,
            True,
            True,
            self.gemini_client is not None,
        )

    def consume(self, event: dict[str, Any]) -> None:
        """Consume a single event in a thread-safe manner.

        Args:
            event: Telemetry event dict.
        """
        with self._lock:
            self.pipeline.consume(event)

    def consume_batch(self, events: list[dict[str, Any]]) -> None:
        """Consume a batch of events (performance-critical path).

        Args:
            events: List of telemetry events.
        """
        start = time.monotonic()
        with self._lock:
            self.pipeline.consume_batch(events)
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.debug("consume_batch processed=%d elapsed_ms=%.2f", len(events), elapsed_ms)

    def reconstruct(self, signal: dict[str, Any], mode: str = "fast") -> dict[str, Any]:
        """Reconstruct incident context.

        Args:
            signal: IncidentSignal dict.
            mode: "fast" or "deep".

        Returns:
            Context dict.
        """
        return self.context_builder.build(signal, mode)

    def shutdown(self) -> None:
        """Gracefully close resources and flush any buffers."""
        with self._lock:
            if hasattr(self.pipeline, "flush"):
                try:
                    self.pipeline.flush()
                except Exception as exc:
                    logger.warning("Pipeline flush failed: %s", exc)

            if hasattr(self.event_store, "close"):
                self.event_store.close()
            if hasattr(self.vector_store, "close"):
                self.vector_store.close()

        logger.info("MemorySubstrate shutdown complete")

    def ingest(self, events: Iterable[dict[str, Any]]) -> None:
        """Backward-compatible alias for consume_batch."""
        self.consume_batch(list(events))

    def reconstruct_context(self, signal: dict[str, Any], mode: str = "fast") -> dict[str, Any]:
        """Backward-compatible alias for reconstruct."""
        return self.reconstruct(signal, mode)

    def close(self) -> None:
        """Backward-compatible alias for shutdown."""
        self.shutdown()
