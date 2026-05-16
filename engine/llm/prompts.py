"""Prompt templates for Gemini reasoning."""

EXPLAIN_PROMPT = """
You are an expert Site Reliability Engineer writing a plain-English summary.

Incident Signal: {signal}

Related Events (chronological):
{related_events}

Causal Chain identified:
{causal_chain}

Similar Past Incidents:
{similar_incidents}

Suggested Remediations:
{remediations}

Write 2-4 short, easy-to-read sentences in simple English. Make it human-friendly:
1) Say what triggered the incident.
2) Explain the likely root cause with one clear piece of evidence.
3) Mention the most similar past incident.
4) End with the recommended action.

Be specific (service names, versions, metrics). Avoid jargon and long clauses.
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
