# Project Structure — Persistent Context Engine

```
persistent-context-engine/
│
├── README.md                          # Quickstart — 5 steps to run
├── PRD.md                             # This product requirements doc
├── Dockerfile                         # Reproducible container
├── docker-compose.yml                 # Optional: if running with services
├── requirements.txt                   # All deps with version pins
├── .env.example                       # GEMINI_API_KEY=your_key_here
│
├── bench/
│   └── run.sh                         # REQUIRED: runs benchmark, emits report.json
│
├── adapters/
│   └── myteam.py                      # REQUIRED: thin shim — implements Adapter base class
│                                      # ingest() and reconstruct_context() live here
│
├── engine/                            # Core engine — all business logic
│   ├── __init__.py
│   │
│   ├── core.py                        # MemorySubstrate — the main engine class
│   │                                  # Coordinates all subsystems
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── pipeline.py                # Event ingestion pipeline
│   │   │                              # Parses, validates, routes events by kind
│   │   ├── handlers.py                # Per-event-kind handlers
│   │   │                              # handle_deploy(), handle_log(), handle_metric()
│   │   │                              # handle_trace(), handle_topology(), handle_remediation()
│   │   └── buffer.py                  # In-memory batch buffer
│   │                                  # Flushes to DuckDB every 2 seconds
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── event_store.py             # DuckDB wrapper
│   │   │                              # store_event(), query_window(), replay()
│   │   └── schema.sql                 # DuckDB table definitions
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── causal_graph.py            # NetworkX DiGraph wrapper
│   │   │                              # add_edge(), traverse(), get_causal_chain()
│   │   ├── alias_registry.py          # Rename/topology drift handler
│   │   │                              # register_rename(), resolve(), get_canonical()
│   │   │                              # Handles chains: A→B→C resolves to A
│   │   └── graph_builder.py           # Builds graph edges from ingested events
│   │                                  # Temporal proximity + trace correlation
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── fingerprint.py             # Behavioral fingerprinting
│   │   │                              # Topology-independent incident signatures
│   │   │                              # extract_fingerprint(), vectorize()
│   │   ├── vector_store.py            # ChromaDB wrapper
│   │   │                              # store_fingerprint(), find_similar()
│   │   └── incident_memory.py         # Long-term incident memory
│   │                                  # remember_incident(), recall_similar()
│   │                                  # Handles rename-robust matching
│   │
│   ├── reconstruction/
│   │   ├── __init__.py
│   │   ├── context_builder.py         # Main reconstruction orchestrator
│   │   │                              # Calls graph, memory, llm in sequence
│   │   │                              # fast mode vs deep mode logic
│   │   ├── event_ranker.py            # Ranks related events by signal density
│   │   │                              # Filters noise, keeps high-signal events
│   │   └── remediation_ranker.py      # Ranks suggested remediations
│   │                                  # Uses historical outcome reinforcement
│   │
│   └── llm/
│       ├── __init__.py
│       ├── gemini_client.py           # Gemini API wrapper
│       │                              # generate_explanation(), build_causal_chain()
│       │                              # Has retry logic + timeout handling
│       └── prompts.py                 # All Gemini prompt templates
│                                      # EXPLAIN_PROMPT, CAUSAL_CHAIN_PROMPT
│                                      # REMEDIATION_PROMPT
│
├── demo/
│   ├── app.py                         # Streamlit demo UI (for demo video only)
│   ├── sample_events.jsonl            # The 7 sample events from problem statement
│   └── scenario_runner.py             # Feeds events into engine for demo
│
└── tests/
    ├── test_alias_registry.py         # Unit tests for rename handling
    ├── test_fingerprint.py            # Unit tests for behavioral fingerprinting
    ├── test_ingest.py                 # Unit tests for event ingestion
    └── test_reconstruct.py            # Integration test for full reconstruction
```

---

## File Responsibilities — Plain English

### `adapters/myteam.py`
The ONLY file the benchmark harness talks to. Thin wrapper — just calls engine methods. Do not put logic here.

### `engine/core.py`
The brain. Holds references to all subsystems. `MemorySubstrate.consume(event)` and `MemorySubstrate.reconstruct(signal, mode)` are the two key methods.

### `engine/graph/alias_registry.py`
THE most important file for scoring. Gets all the rename events, keeps a dict like:
```python
{
  "billing-svc": "payments-svc",   # billing-svc IS payments-svc
  "pay-api": "payments-svc",       # transitive chain resolved
}
```
Every graph query runs through this first.

### `engine/memory/fingerprint.py`
Second most important file. Converts an incident into a topology-independent vector:
```python
# NOT this (topology-dependent, breaks on rename):
["payments-svc", "deploy", "checkout-api", "error"]

# THIS (topology-independent, survives rename):
{
  "pattern": ["deploy", "latency_spike", "upstream_error"],
  "severity": "high",
  "trigger_type": "error_rate",
  "resolution": "rollback",
  "time_to_trigger_mins": 10
}
```

### `engine/llm/gemini_client.py`
Calls Gemini API. Only used in `deep` mode and for generating the `explain` field. Has a 1.5s timeout for fast mode compatibility.

### `demo/app.py`
Streamlit UI — only for the 5-minute demo video. Not judged. Shows the memory graph visually and the output of reconstruct_context() in a readable way.

---

## Data Flow — Step by Step

```
1. Events arrive as JSONL stream
         ↓
2. pipeline.py parses and validates each event
         ↓
3. handlers.py routes by event.kind:
   - deploy/log/metric/trace → event_store.py (DuckDB) + graph_builder.py (edges)
   - topology rename → alias_registry.py (merge nodes)
   - incident_signal → incident_memory.py (start tracking)
   - remediation → incident_memory.py (record outcome) + remediation_ranker.py
         ↓
4. fingerprint.py continuously updates behavioral fingerprints
         ↓
5. vector_store.py stores fingerprints in ChromaDB
         ↓
─── INCIDENT FIRES ───
         ↓
6. context_builder.py called with IncidentSignal
         ↓
7. alias_registry.py resolves service name → canonical name
         ↓
8. event_store.py fetches events in ±10 min window
         ↓
9. causal_graph.py traverses edges → causal_chain
         ↓
10. vector_store.py finds similar past fingerprints → similar_past_incidents
         ↓
11. remediation_ranker.py ranks fixes by historical success → suggested_remediations
         ↓
12. [DEEP MODE ONLY] gemini_client.py generates explain narrative
         ↓
13. Returns Context TypedDict to adapter
```

---

## Environment Variables

```bash
# .env
GEMINI_API_KEY=your_gemini_api_key_here
CHROMA_PERSIST_DIR=./data/chroma
DUCKDB_PATH=./data/events.db
LOG_LEVEL=INFO
FAST_MODE_TIMEOUT_S=1.8
DEEP_MODE_TIMEOUT_S=5.5
```

---

## Build Order (What to Code First)

Build in this exact order — each step is testable before moving to next:

```
Step 1  →  schema.py alignment         Make sure your TypedDicts match harness exactly
Step 2  →  event_store.py              DuckDB setup, store and query events
Step 3  →  alias_registry.py           Rename handling — most critical logic
Step 4  →  pipeline.py + handlers.py   Ingest pipeline working end-to-end
Step 5  →  causal_graph.py             Build graph from events
Step 6  →  fingerprint.py              Topology-independent signatures
Step 7  →  vector_store.py             ChromaDB integration
Step 8  →  incident_memory.py          Connect fingerprints to incidents
Step 9  →  context_builder.py          Wire everything together
Step 10 →  gemini_client.py            Add LLM for explain field
Step 11 →  adapters/myteam.py          Wire to harness interface
Step 12 →  self_check.py run           Iterate on weak metrics
Step 13 →  demo/app.py                 Streamlit UI for video
Step 14 →  Dockerfile + README         Submission packaging
```

---

## Key Design Decisions

### Why DuckDB over SQLite?
DuckDB handles 1000+ events/sec ingestion with columnar storage. SQLite is row-oriented and slower for analytical queries (time window lookups). DuckDB runs in-process — no server.

### Why NetworkX over Neo4j?
Neo4j requires a running server which complicates Docker and adds startup time. NetworkX is pure Python, runs in memory, instant startup. Fast enough for 12–20 services over 7–14 days.

### Why ChromaDB over Qdrant?
ChromaDB runs fully in-process and persists to disk. No server, no port, works inside Docker with zero config. Qdrant needs a separate container.

### Why Gemini Flash over GPT-4?
- Faster (important for 2s budget)
- Cheaper (important since we pay our own API costs)
- Good enough for explanation generation
- Use `gemini-1.5-flash` for fast mode, `gemini-1.5-pro` for deep mode

### Why NOT use the baseline vector similarity?
The problem statement says submissions that wrap it without architectural innovation rank near the bottom. Our differentiator is the alias registry + topology-independent fingerprinting, which the baseline does not have.
