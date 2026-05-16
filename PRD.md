# PRD — Persistent Context Engine
## Hackathon: Anvil Problem 02 / 04 — Open Track
**Time budget:** 24 hours | **Team size:** 1–4 | **LLM:** Gemini API

---

## 1. What We Are Building

A Python-based **operational memory engine** that:
1. **Ingests** a continuous stream of infrastructure telemetry events (deploys, logs, metrics, traces, topology changes, incidents, remediations)
2. **Builds** a persistent causal memory graph of relationships between those events
3. **Reconstructs** investigation context in under 2 seconds when an incident fires — including causal chain, similar past incidents, and suggested remediations
4. **Survives topology drift** — if `payments-svc` is renamed to `billing-svc`, the engine still recognises the same failure pattern

This is NOT a dashboard. NOT a log viewer. NOT a search wrapper. It is an operational memory engine.

---

## 2. The Two Methods We Must Implement

The entire submission is judged on exactly two Python methods:

```python
def ingest(self, events: Iterable[Event]) -> None:
    # Consume telemetry stream, build memory graph

def reconstruct_context(self, signal: IncidentSignal, mode="fast") -> Context:
    # At incident time, return structured operational context
```

### Output shape (must match exactly):
```python
class Context(TypedDict):
    related_events:         list[Event]         # ordered, deduped, with provenance
    causal_chain:           list[CausalEdge]    # (cause_id, effect_id, evidence, confidence)
    similar_past_incidents: list[IncidentMatch] # (past_incident_id, similarity, rationale)
    suggested_remediations: list[Remediation]   # (action, target, historical_outcome, confidence)
    confidence:             float               # 0.0 to 1.0
    explain:                str                 # human-readable narrative
```

---

## 3. Input Event Types (6 Guaranteed)

| kind | Key fields | What it means |
|------|-----------|---------------|
| `deploy` | service, version, actor | Code was deployed |
| `log` | service, level, msg, trace_id | A log line was emitted |
| `metric` | service, name, value | A metric value was recorded |
| `trace` | trace_id, spans[{svc, dur_ms}] | A distributed trace |
| `topology` | change, from, to | Service renamed or dependency changed |
| `incident_signal` | incident_id, trigger | An alert fired |
| `remediation` | incident_id, action, target, version, outcome | A fix was applied |

---

## 4. Architecture — Three Layers

### Layer 1: Ingest & Storage
- **SQLite** (via DuckDB) — fast, local, no server needed, stores raw events with timestamps
- **In-memory graph** (Python dict of dicts) — nodes = services, edges = causal relationships
- **Alias registry** — tracks all renames: `payments-svc → billing-svc`

### Layer 2: Memory & Fingerprinting
- **Behavioral fingerprint** per incident — topology-independent pattern signature
  - Pattern: `[deploy, latency_spike, upstream_error]` NOT `[payments-svc, checkout-api]`
  - Stored as a feature vector, compared via cosine similarity
- **ChromaDB** — vector store for fingerprint similarity search
- **Causal graph** — directed edges: `deploy_event → metric_spike → log_error`

### Layer 3: Reconstruction (Gemini API)
- On `reconstruct_context()` call:
  1. Fetch temporally related events (±10 min window)
  2. Resolve aliases (billing-svc = payments-svc)
  3. Query ChromaDB for similar past fingerprints
  4. Build causal chain from graph edges
  5. Call Gemini to generate the `explain` narrative and fill confidence gaps
  6. Return structured `Context` object

---

## 5. The Rename Problem — Core Solution

When a `topology` rename event arrives:
```json
{"kind":"topology","change":"rename","from":"payments-svc","to":"billing-svc"}
```

We do THREE things:
1. **Alias registry**: store `billing-svc → payments-svc` (canonical name)
2. **Graph merge**: merge the two service nodes, preserve all edges
3. **Fingerprint independence**: fingerprints use ROLE tags not service names
   - Instead of `"payments-svc had deploy"` → store `"SERVICE_A had deploy"`
   - This means a billing-svc deploy fingerprint matches a payments-svc deploy fingerprint

---

## 6. Latency Requirements

| Operation | Requirement | Our approach |
|-----------|-------------|--------------|
| Ingest throughput | ≥ 1,000 events/sec | Batch inserts, async graph updates |
| Ingest lag | ≤ 5 seconds | In-memory buffer, flush every 2s |
| reconstruct fast | p95 ≤ 2 seconds | Pre-computed fingerprints, cached graph |
| reconstruct deep | p95 ≤ 6 seconds | Full Gemini call + deeper traversal |
| Cold start | ≤ 60 seconds | Lazy loading, SQLite for persistence |

---

## 7. Scoring Metrics We Must Hit

| Metric | What it measures | Our strategy |
|--------|-----------------|--------------|
| `precision@5` | Did top-5 similar incidents include correct match? | ChromaDB cosine similarity on behavioral fingerprints |
| `recall@5` | Did we miss any correct matches in top-5? | Alias-resolved graph traversal |
| `remediation_acc` | Did we suggest the right fix? | Reinforcement from past `remediation` outcomes |
| `latency_p95` | Speed of reconstruct_context | In-memory caching |
| `pattern F1` | Incident family classification | Topology-independent fingerprinting |
| `temporal %` | Causal edges in correct time order | Timestamp-sorted edge insertion |
| `Δ-adaptability` | Score drop after topology drift | Alias registry + graph merge |
| `explain grade` | Human-readable narrative quality | Gemini generates this |

---

## 8. What We Are NOT Building

- ❌ No auto-remediation (diagnosis only)
- ❌ No real-time streaming infra (Kafka, Flink) — overkill for 24h
- ❌ No cloud deployment — runs locally
- ❌ No web UI required for judging — Streamlit only for demo video

---

## 9. Demo Flow (5-min video)

1. **(0:00–1:00)** Feed sample JSONL into engine, show ingest working
2. **(1:00–2:00)** Show the memory graph building (Neo4j browser or printed graph)
3. **(2:00–3:00)** Fire the rename event — show alias registry updating
4. **(3:00–4:00)** Fire INC-714 incident signal — show reconstruct_context() running
5. **(4:00–5:00)** Show output: causal chain + similar past incidents + remediation suggestion

---

## 10. Tech Stack

| Component | Tool | Why |
|-----------|------|-----|
| Core language | Python 3.11 | Required by harness |
| Raw event storage | DuckDB (in-process) | Fast, no server, SQL queries |
| Causal graph | NetworkX | Pure Python graph, no server |
| Vector similarity | ChromaDB | Local vector store, no server |
| LLM reasoning | Gemini 1.5 Flash API | Fast, cheap, good reasoning |
| Demo UI | Streamlit | Dead simple Python UI |
| Containerisation | Docker | Required for reproducibility |

---

## 11. Submission Checklist

- [ ] `adapters/myteam.py` — implements `ingest()` and `reconstruct_context()`
- [ ] `bench/run.sh` — runs benchmark, emits JSON report
- [ ] `Dockerfile` — reproducible environment
- [ ] `README.md` — quickstart in 5 steps
- [ ] `requirements.txt` — all deps with version pins
- [ ] 5-min demo video (screen recording)
- [ ] 3-page PDF writeup

---

## 12. Risk & Mitigations

| Risk | Mitigation |
|------|-----------|
| Gemini API too slow for 2s budget | Cache Gemini calls; use fast mode without Gemini, deep mode with Gemini |
| ChromaDB cold start slow | Pre-load on `__init__`, persist to disk |
| Rename chain (A→B→C) breaks alias resolution | Transitive alias resolution in registry |
| Graph too large for memory | Prune edges older than 30 days, keep incident nodes forever |
| Benchmark seeds differ wildly | No hardcoding — all logic is pattern-based not string-match |
