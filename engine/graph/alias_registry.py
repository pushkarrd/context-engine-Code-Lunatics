"""Topology drift handler — tracks service renames and aliases."""
from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any


class AliasRegistry:
    """Tracks service name aliases and resolves renames.

    This registry keeps a canonical name for each service and maps any renamed
    aliases back to the original. It supports transitive rename chains.

    Example:
        >>> from datetime import datetime
        >>> registry = AliasRegistry()
        >>> registry.register_rename("payments-svc", "billing-svc", datetime.utcnow())
        >>> registry.resolve("billing-svc")
        'payments-svc'
        >>> registry.is_same_service("payments-svc", "billing-svc")
        True
    """

    def __init__(self) -> None:
        """Initialize empty alias registry."""
        self._alias_to_canonical: dict[str, str] = {}
        self._canonical_to_aliases: dict[str, set[str]] = {}
        self._rename_history: dict[str, list[dict[str, Any]]] = {}
        self._lock = Lock()

    def register_rename(self, from_name: str, to_name: str, ts: datetime) -> None:
        """Record a service rename at a given time.

        Chains are resolved so that the canonical name is always the earliest
        name in the chain. If A→B and B→C, then resolve(C) returns A.

        Args:
            from_name: Old service name.
            to_name: New service name.
            ts: Timestamp of the rename event.
        """
        if not from_name or not to_name:
            return

        with self._lock:
            canonical = self._resolve_unlocked(from_name)
            alias = to_name

            # No-op if alias already resolves to canonical.
            if self._resolve_unlocked(alias) == canonical:
                return

            self._alias_to_canonical[alias] = canonical
            self._canonical_to_aliases.setdefault(canonical, set()).add(alias)

            history = self._rename_history.setdefault(canonical, [])
            history.append({"from": from_name, "to": to_name, "ts": ts})

    def resolve(self, name: str) -> str:
        """Resolve a service name to its canonical form.

        Args:
            name: Service name (alias or canonical).

        Returns:
            Canonical service name.
        """
        if not name:
            return name
        with self._lock:
            return self._resolve_unlocked(name)

    def get_all_aliases(self, canonical: str) -> list[str]:
        """Return all known names for a canonical service.

        Args:
            canonical: Canonical or alias name.

        Returns:
            List of all known names, including the canonical name.
        """
        if not canonical:
            return []
        with self._lock:
            base = self._resolve_unlocked(canonical)
            aliases = self._canonical_to_aliases.get(base, set())
            return sorted({base, *aliases})

    def resolve_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Resolve service-related fields in an event.

        The returned event preserves the original service in `_original_service`.

        Args:
            event: Event dict to resolve.

        Returns:
            A new event dict with canonical service names.
        """
        if not event:
            return {}

        resolved = dict(event)
        with self._lock:
            service = resolved.get("service")
            if service:
                resolved["_original_service"] = service
                resolved["service"] = self._resolve_unlocked(service)

            for key in ("target", "from_", "to"):
                value = resolved.get(key)
                if value:
                    resolved[key] = self._resolve_unlocked(value)

        return resolved

    def get_rename_history(self, service: str) -> list[dict[str, Any]]:
        """Return rename events for a service.

        Args:
            service: Canonical or alias name.

        Returns:
            List of rename records: {from, to, ts}.
        """
        if not service:
            return []
        with self._lock:
            canonical = self._resolve_unlocked(service)
            return list(self._rename_history.get(canonical, []))

    def is_same_service(self, name_a: str, name_b: str) -> bool:
        """Check whether two names resolve to the same canonical service.

        Args:
            name_a: First service name.
            name_b: Second service name.

        Returns:
            True if both resolve to the same canonical service.
        """
        if not name_a or not name_b:
            return False
        with self._lock:
            return self._resolve_unlocked(name_a) == self._resolve_unlocked(name_b)

    def _resolve_unlocked(self, name: str) -> str:
        """Resolve without acquiring the lock; caller must hold lock."""
        current = name
        seen: set[str] = set()
        while current in self._alias_to_canonical:
            if current in seen:
                break
            seen.add(current)
            current = self._alias_to_canonical[current]
        return current
