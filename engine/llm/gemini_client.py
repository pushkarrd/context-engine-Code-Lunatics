"""Gemini API client for explanation and causal enhancement."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from engine.llm.prompts import CAUSAL_CHAIN_PROMPT, EXPLAIN_PROMPT


class GeminiClient:
    """Wrapper for Gemini API used in context reconstruction."""

    def __init__(self, api_key: str | None = None, timeout_s: float = 5.0) -> None:
        """Initialize Gemini client.

        Args:
            api_key: Gemini API key (or GEMINI_API_KEY env).
            timeout_s: Soft timeout for API calls.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.timeout_s = timeout_s
        self._client_ready = False

        if not self.api_key:
            return

        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        self._fast_model = genai.GenerativeModel("gemini-1.5-flash")
        self._deep_model = genai.GenerativeModel("gemini-1.5-pro")
        self._client_ready = True

    def generate_explanation(
        self,
        signal: dict[str, Any],
        related_events: list[dict[str, Any]],
        causal_chain: list[dict[str, Any]],
        similar_incidents: list[dict[str, Any]],
        suggested_remediations: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Generate an explanation narrative for the incident.

        Args:
            signal: Incident signal.
            related_events: Related events (chronological).
            causal_chain: Current causal chain.
            similar_incidents: Similar incidents from memory.
            suggested_remediations: Suggested remediation actions.

        Returns:
            Human-readable explanation string.
        """
        if not self._client_ready:
            return self._fallback_explanation(signal, similar_incidents)

        mode = str(signal.get("mode", "deep")).lower()
        model = self._fast_model if mode == "fast" else self._deep_model

        prompt = EXPLAIN_PROMPT.format(
            signal=_safe_json(signal),
            related_events=_safe_json(related_events, limit=40),
            causal_chain=_safe_json(causal_chain, limit=20),
            similar_incidents=_safe_json(similar_incidents, limit=10),
            remediations=_safe_json(suggested_remediations, limit=10),
        )

        start = time.monotonic()
        try:
            response = self._call_with_backoff(model, prompt)
            elapsed = time.monotonic() - start
            if elapsed > self.timeout_s:
                return self._fallback_explanation(signal, similar_incidents)
            return response.strip() if response else self._fallback_explanation(signal, similar_incidents)
        except Exception:
            return self._fallback_explanation(signal, similar_incidents)

    def enhance_causal_chain(
        self,
        events: list[dict[str, Any]],
        existing_chain: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ask Gemini to enhance the causal chain with additional edges.

        Args:
            events: Related events.
            existing_chain: Current causal chain.

        Returns:
            Enhanced causal chain, or existing chain on error.
        """
        if not self._client_ready:
            return existing_chain

        prompt = CAUSAL_CHAIN_PROMPT.format(
            related_events=_safe_json(events, limit=60),
            causal_chain=_safe_json(existing_chain, limit=20),
        )

        try:
            response = self._call_with_backoff(self._deep_model, prompt)
            parsed = _parse_json_list(response)
            return parsed if parsed is not None else existing_chain
        except Exception:
            return existing_chain

    def is_available(self) -> bool:
        """Return True if API key is set and Gemini is reachable."""
        if not self._client_ready:
            return False

        try:
            response = self._call_with_backoff(self._fast_model, "ping")
            return bool(response)
        except Exception:
            return False

    def _call_with_backoff(self, model: Any, prompt: str) -> str:
        """Call Gemini with exponential backoff (max 2 retries)."""
        delay = 0.5
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                response = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.3, "max_output_tokens": 400},
                )
                return response.text if response else ""
            except Exception as exc:  # pragma: no cover - depends on API
                last_error = exc
                if attempt < 2:
                    time.sleep(delay)
                    delay *= 2
                else:
                    break

        if last_error:
            raise last_error
        return ""

    def _fallback_explanation(self, signal: dict[str, Any], similar_incidents: list[dict[str, Any]]) -> str:
        """Fallback explanation when Gemini is unavailable."""
        service = signal.get("service", "unknown")
        trigger = signal.get("trigger", "unknown")
        if similar_incidents:
            top = similar_incidents[0]
            return (
                f"Incident in {service} triggered by {trigger}. "
                f"Similar to {top.get('past_incident_id', 'unknown')} pattern."
            )
        return f"Incident in {service} triggered by {trigger}."


def _safe_json(value: Any, limit: int | None = None) -> str:
    if isinstance(value, list) and limit is not None:
        value = value[:limit]
    return json.dumps(value, indent=2, default=str)


def _parse_json_list(text: str) -> list[dict[str, Any]] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        return None
    return None
