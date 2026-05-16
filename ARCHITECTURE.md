# Architecture — Persistent Context Engine

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      TELEMETRY INGEST                           │
│  (deploys, logs, metrics, traces, topology, incidents, fixes)   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                 INGESTION PIPELINE                              │
│  • Validate events                                              │
│  • Route by kind (deploy|log|metric|trace|topology|etc)        │
│  • DuckDB storage + Graph updates                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
          ┌─────────────────┐   ┌──────────────────┐
          │  EVENT STORE    │   │ ALIAS REGISTRY   │
          │  (DuckDB)       │   │ (Renames)        │
          │                 │   │                  │
          │ +events table   │   │ A→B→C = C        │
          │ +indexes (ts,   │   │ (transitive)     │
          │  kind, service) │   │                  │
          └────────┬────────┘   └──────────────────┘
                   │
                   ▼
          ┌──────────────────┐
          │  FINGERPRINTING  │
          │                  │
          │ Pattern: [deploy,│
          │  latency,error]  │
          │                  │
          │ (not service     │
          │  names!)         │
          │                  │
          │ Vector: [0.8,    │
          │  0.6, 0.9, ...]  │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │  VECTOR STORE    │
          │  (ChromaDB)      │
          │                  │
          │ Cosine similarity│
          │ search on        │
          │ fingerprints     │
          └──────────────────┘


        INCIDENT FIRES (IncidentSignal)
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                CONTEXT RECONSTRUCTION                           │
│                                                                 │
│  1. Resolve service → canonical (alias_registry)               │
│  2. Query event_store for ±10 min window                      │
│  3. Extract current fingerprint                                │
│  4. Vector store finds similar past incidents                 │
│  5. Causal graph returns cause-effect chain                   │
│  6. Rank remediations by historical success                   │
│  7. [Deep mode] Gemini generates narrative                    │
│                                                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  CONTEXT OUTPUT │
                    │                 │
                    │ {               │
                    │   related_      │
                    │   events: […]  │
                    │   causal_chain  │
                    │   similar_      │
                    │   past_...      │
                    │   suggested_    │
                    │   remediations  │
                    │   confidence    │
                    │   explain       │
                    │ }               │
                    └─────────────────┘
```

---

## Component Breakdown

### 1. **Storage Layer**
```python
engine/storage/
├── event_store.py      # DuckDB wrapper
│   └── Methods:
│       - store_event()
│       - query_window()
│       - get_events_for_incident()
│       - count_events()
│
└── schema.sql          # Table definitions + indexes
    └── events table: (id, ts, kind, service, …)
        - Index on ts (time range queries)
        - Index on service (event lookup)
        - Index on incident_id (incident tracking)
```

**Why DuckDB?**
- Columnar storage (fast time-range queries)
- In-process (no server)
- OLAP-optimized (analytical queries)
- 1000+ events/sec throughput

---

### 2. **Graph Layer**
```python
engine/graph/
├── alias_registry.py   # Topology drift handling ⭐
│   └── Core logic:
│       - register_rename(from, to)
│       - resolve(name) → canonical
│       - get_all_aliases_for(canonical)
│
└── causal_graph.py     # NetworkX DiGraph
    └── Methods:
        - add_edge(cause_id, effect_id, evidence, conf)
        - get_causal_chain(event_id, depth)
        - count_nodes(), count_edges()
```

**Topology Drift Example:**
```
Events: rename(payments-svc → billing-svc)
        rename(billing-svc → checkout-api)

Alias Registry tracks:
  payments-svc → billing-svc
  billing-svc  → checkout-api

Result:
  resolve("payments-svc")  = "checkout-api"
  resolve("billing-svc")   = "checkout-api"
  resolve("checkout-api")  = "checkout-api"
```

---

### 3. **Memory Layer**
```python
engine/memory/
├── fingerprint.py      # Topology-independent signatures ⭐
│   └── Steps:
│       1. Sort events by timestamp
│       2. Extract pattern: [deploy, log, metric, …]
│       3. Infer severity from error levels
│       4. Infer trigger & resolution
│       5. Convert to vector: [0.8, 0.6, 0.2, …]
│
├── vector_store.py     # ChromaDB integration
│   └── Methods:
│       - store_fingerprint(incident_id, vector)
│       - find_similar(query_vector, k=5)
│
└── incident_memory.py
    └── Methods:
        - remember_incident(…)
        - record_remediation(…)
        - recall_similar(fingerprint) → [(id, similarity, …)]
```

**Fingerprint Example:**
```
Incident INC-100 (old):
  Events: deploy → 500ms latency spike → error log
  Service: payments-svc

Fingerprint (topology-independent):
  {
    "pattern": ["deploy", "metric", "log"],
    "severity": "high",
    "trigger_type": "latency",
    "resolution": "rollback",
  }
  Vector: [0.8, 0.6, 0.9, 0.7, …]

Later, service renamed to billing-svc:
Incident INC-200 (new):
  Events: deploy → 520ms latency spike → error log
  Service: billing-svc

  Fingerprint:
  {
    "pattern": ["deploy", "metric", "log"],
    "severity": "high",
    "trigger_type": "latency",
    "resolution": "rollback",
  }
  Vector: [0.79, 0.61, 0.88, 0.68, …]  ← Very similar!

  Cosine similarity(INC-100, INC-200) = 0.95
  Result: INC-100 is found as "similar past incident"
```

---

### 4. **Ingestion Layer**
```python
engine/ingestion/
├── pipeline.py         # Event validation + routing
│   └── ingest_events(iterable) → count
│       - Validate by kind
│       - Check required fields
│       - Call appropriate handler
│
└── handlers.py         # Kind-specific processing
    ├── handle_deploy()     → event_store + graph
    ├── handle_log()        → event_store
    ├── handle_metric()     → event_store
    ├── handle_trace()      → build edges from spans
    ├── handle_topology()   → alias_registry.register_rename()
    ├── handle_incident_signal()   → trigger fingerprinting
    └── handle_remediation()       → record outcome
```

---

### 5. **Reconstruction Layer**
```python
engine/reconstruction/
├── context_builder.py  # Orchestrator
│   └── build_context(signal, mode) → Context
│       1. Resolve service name (alias_registry)
│       2. Fetch related events (event_store)
│       3. Extract fingerprint (fingerprint.py)
│       4. Find similar incidents (vector_store)
│       5. Build causal chain (causal_graph)
│       6. Suggest remediations (incident_memory)
│       7. Generate explanation (gemini_client)
│
└── event_ranker.py     # Signal filtering
    └── rank_events(events, limit) → ranked_events
        - Deploy: +0.3
        - Error log: +0.2
        - High metric: +0.2
        - Incident signal: +0.4
```

---

### 6. **LLM Layer**
```python
engine/llm/
└── gemini_client.py    # Gemini 1.5 Flash wrapper
    └── generate_explanation(…, timeout_s) → narrative
        - Summarize events
        - Summarize causal chain
        - Summarize similar incidents
        - Feed to Gemini with timeout
        - Fallback if timeout exceeded
```

---

## Latency Budgets

| Mode | Budget | Strategy |
|------|--------|----------|
| **Fast** | <2s | In-memory graph + pre-computed fingerprints + NO LLM |
| **Deep** | <6s | Same as fast, but with Gemini (if time permits) |

Gemini call timeout: `remaining_budget - 0.5s` (to ensure response generation time)

---

## Data Structures

### EventStore Queries
```sql
-- Incident window query
SELECT * FROM events
WHERE service IN (SELECT DISTINCT service FROM events
                  WHERE incident_id = ?)
  AND ts BETWEEN ? AND ?
ORDER BY ts ASC

-- Time range query
SELECT * FROM events
WHERE ts BETWEEN ? AND ?
  AND kind = 'metric'
ORDER BY ts DESC
LIMIT 50
```

### Graph Representation
```python
# NetworkX DiGraph
Graph.nodes = {event_id_1, event_id_2, …}
Graph.edges = {
  (event_1, event_2): {"evidence": "str", "confidence": 0.8},
  (event_2, event_3): {"evidence": "str", "confidence": 0.6},
}
```

### ChromaDB Collections
```python
collection = client.get_or_create_collection(
    name="incident_fingerprints",
    metadata={"hnsw:space": "cosine"}
)
collection.add(
    ids=[incident_id],
    embeddings=[fingerprint_vector],
    metadatas=[{"pattern", "severity", "trigger_type", …}],
    documents=[str(fingerprint_dict)]
)
```

---

## Scoring Alignment

The engine returns Context that maps directly to scoring:

```python
# Scoring code (from metrics.py):
def score_match(ctx, ground_truth, k=5):
    matches = ctx.get("similar_past_incidents")[:k]
    target = ground_truth["family"]
    in_top_k = any(_family_from_incident_id(m["incident_id"]) == target for m in matches)
    precision = sum(…) / k
    return in_top_k, precision

def score_remediation(ctx, ground_truth):
    expected = ground_truth["expected_remediation"]
    return any(s["action"] == expected for s in ctx.get("suggested_remediations"))
```

**Our engine provides:**
- ✅ `similar_past_incidents` with correct `incident_id` format → recall@5, precision
- ✅ `suggested_remediations` with `action` field → remediation_acc

---

## Production Deployment Checklist

- ✅ Type hints throughout
- ✅ Error handling + fallbacks
- ✅ Timeout safety on LLM calls
- ✅ Logging at key points
- ✅ In-process (no external servers)
- ✅ Deterministic (reproducible with seeds)
- ✅ Lazy imports (avoid circular deps)
- ✅ No hardcoded service names (all pattern-based)

---

**For questions, see `IMPLEMENTATION_SUMMARY.md` or `README.md`**
