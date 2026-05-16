"""Streamlit demo UI for the Persistent Context Engine."""
from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import streamlit as st

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from adapters.myteam import Engine


st.set_page_config(page_title="Persistent Context Engine", layout="wide")


def _parse_ts(ts: str | None) -> str:
    if not ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts


def _parse_json_input(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            payload = json.loads(text)
            return [e for e in payload if isinstance(e, dict)]
        except json.JSONDecodeError:
            return []

    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            continue

    return events


def _load_jsonl(uploaded) -> list[dict[str, Any]]:
    if not uploaded:
        return []
    data = uploaded.read().decode("utf-8")
    return _parse_json_input(data)


def _event_service_set(events: list[dict[str, Any]]) -> set[str]:
    services = set()
    for event in events:
        service = event.get("service") or event.get("target") or event.get("from_") or event.get("to")
        if service:
            services.add(service)
    return services


def _format_context_json(context: dict[str, Any]) -> dict[str, Any]:
    if not context:
        return {}
    return {
        "related_events": context.get("related_events", []),
        "causal_chain": context.get("causal_chain", []),
        "similar_past_incidents": context.get("similar_past_incidents", []),
        "suggested_remediations": context.get("suggested_remediations", []),
        "confidence": context.get("confidence", 0.0),
        "explain": context.get("explain", ""),
    }


if "engine" not in st.session_state:
    st.session_state.engine = Engine()

if "events" not in st.session_state:
    st.session_state.events = []

if "context" not in st.session_state:
    st.session_state.context = None


engine = st.session_state.engine


with st.sidebar:
    st.header("Feed Events")
    uploaded = st.file_uploader("Upload .jsonl", type=["jsonl"])
    pasted = st.text_area("Or paste JSON events", height=180)

    if st.button("▶ Ingest Events"):
        events = []
        if uploaded:
            events.extend(_load_jsonl(uploaded))
        if pasted:
            events.extend(_parse_json_input(pasted))

        for event in events:
            event.setdefault("ts", _parse_ts(event.get("ts")))

        if events:
            engine.ingest(events)
            st.session_state.events.extend(events)

    graph_nodes = 0
    services = _event_service_set(st.session_state.events)
    if hasattr(engine.store, "causal_graph"):
        graph = engine.store.causal_graph.graph
        graph_nodes = graph.number_of_nodes()

    status = f"✅ {len(st.session_state.events)} events ingested | {graph_nodes} graph nodes | {len(services)} services tracked"
    st.caption(status)


st.title("Persistent Context Engine Demo")


tabs = st.tabs([
    "🚨 Trigger Incident",
    "🧠 Reconstructed Context",
    "🕸️ Memory Graph",
    "📋 Raw Events",
])


with tabs[0]:
    col1, col2 = st.columns(2)
    with col1:
        incident_id = st.text_input("Incident ID", value="INC-714")
        service = st.text_input("Service", value="billing-svc")
    with col2:
        trigger = st.text_input("Trigger", value="alert:checkout-api/error-rate>5%")
        mode = st.radio("Mode", options=["fast", "deep"], horizontal=True)

    if st.button("🔍 Reconstruct Context"):
        signal = {
            "incident_id": incident_id,
            "service": service,
            "trigger": trigger,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with st.spinner("Reconstructing context..."):
            st.session_state.context = engine.reconstruct_context(signal, mode=mode)


with tabs[1]:
    context = st.session_state.context
    if not context:
        st.info("Run a reconstruction to see context details.")
    else:
        st.subheader("Context JSON")
        st.json(_format_context_json(context))

        st.subheader("Causal Chain")
        chain = context.get("causal_chain", [])
        if chain:
            for edge in chain:
                cause = edge.get("cause_id") or edge.get("cause_event_id")
                effect = edge.get("effect_id") or edge.get("effect_event_id")
                confidence = edge.get("confidence", 0.0)
                st.write(f"{cause} → {effect} ({confidence:.0%})")
        else:
            st.caption("No causal edges identified.")

        st.subheader("Similar Past Incidents")
        similar = context.get("similar_past_incidents", [])
        if similar:
            st.dataframe(similar, use_container_width=True)
        else:
            st.caption("No similar incidents found.")

        st.subheader("Suggested Remediations")
        remediations = context.get("suggested_remediations", [])
        if remediations:
            top = remediations[0]
            st.success(
                f"Top recommendation: {top.get('action', 'unknown')} → {top.get('target', 'unknown')}"
            )
            st.dataframe(remediations, use_container_width=True)
        else:
            st.caption("No remediation suggestions available.")

        st.subheader("Explanation")
        st.info(context.get("explain", "No explanation."))

        confidence = context.get("confidence", 0.0)
        st.progress(min(max(float(confidence), 0.0), 1.0))


with tabs[2]:
    st.subheader("Memory Graph")
    if hasattr(engine.store, "causal_graph"):
        graph = engine.store.causal_graph.graph
        try:
            from pyvis.network import Network

            net = Network(height="500px", width="100%", directed=True)
            aliases = engine.store.alias_registry

            for node, data in graph.nodes(data=True):
                service = data.get("service")
                label = str(node)
                if service:
                    label = service
                    aliases_list = []
                    if hasattr(aliases, "get_all_aliases"):
                        aliases_list = aliases.get_all_aliases(service)
                    if aliases_list and len(aliases_list) > 1:
                        prev = ", ".join(a for a in aliases_list if a != service)
                        label = f"{service} (was: {prev})"
                net.add_node(node, label=label)

            for src, dst, edge_data in graph.edges(data=True):
                net.add_edge(src, dst, title=edge_data.get("evidence", ""))

            html = net.generate_html()
            st.components.v1.html(html, height=520, scrolling=True)
        except Exception:
            st.info("Graph visualization requires pyvis. Install with `pip install pyvis`.")
    else:
        st.info("Graph not available yet.")


with tabs[3]:
    st.subheader("Raw Events")
    events = st.session_state.events
    if not events:
        st.caption("No events ingested yet.")
    else:
        kinds = sorted({e.get("kind", "unknown") for e in events})
        kind_filter = st.selectbox("Filter by kind", options=["all", *kinds])
        filtered = events
        if kind_filter != "all":
            filtered = [e for e in events if e.get("kind") == kind_filter]

        st.dataframe(filtered, use_container_width=True)
