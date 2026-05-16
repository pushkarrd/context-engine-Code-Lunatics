"""Prompt templates for Gemini reasoning."""

EXPLAIN_PROMPT = """
You are an expert Site Reliability Engineer analyzing a production incident.

Incident Signal: {signal}

Related Events (chronological):
{related_events}

Causal Chain identified:
{causal_chain}

Similar Past Incidents:
{similar_incidents}

Suggested Remediations:
{remediations}

Write a concise incident summary (3-5 sentences) that:
1. States what triggered the incident
2. Explains the root cause with evidence
3. References the most similar past incident
4. Recommends the specific remediation action

Be specific. Use service names, versions, metrics. No generic advice.
"""

CAUSAL_CHAIN_PROMPT = """
You are an expert Site Reliability Engineer reviewing telemetry data.

Related Events (chronological):
{related_events}

Existing Causal Chain:
{causal_chain}

Identify any additional causal edges that are missing. Return a JSON list
of objects with keys: cause_id, effect_id, evidence, confidence (0.0-1.0).
Return an empty list if no additional edges are needed.
"""
