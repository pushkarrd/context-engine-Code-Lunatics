<div align="center">

# 🧠 Persistent Context Engine

### *Operational Memory for Infrastructure — Never Lose Context Again*

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/Gemini_1.5_Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/technologies/gemini/)
[![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)](https://duckdb.org/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-FF6B35?style=for-the-badge&logo=databricks&logoColor=white)](https://www.trychroma.com/)
[![NetworkX](https://img.shields.io/badge/NetworkX-008080?style=for-the-badge&logo=graphql&logoColor=white)](https://networkx.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Railway](https://img.shields.io/badge/Deployed_on_Railway-0B0D0E?style=for-the-badge&logo=railway&logoColor=white)](https://context-engine-code-lunatics-production.up.railway.app/)
[![Live Demo](https://img.shields.io/badge/🟢_Live-context--engine-brightgreen?style=for-the-badge)](https://context-engine-code-lunatics-production.up.railway.app/)

---

**Anvil Hackathon — Problem 02/04 · Open Track**

> *"Incidents don't happen in isolation — they echo. The Persistent Context Engine makes sure your infra never forgets."*

| 🌐 Live App | 🎥 Demo Video | 📄 Problem Statement |
|:-----------:|:-------------:|:--------------------:|
| [**Open Deployed App ↗**](https://context-engine-code-lunatics-production.up.railway.app/) | [**Watch Demo Video ↗**](https://drive.google.com/file/d/1j2_MdsQ70vj6eN5-1xolbKCWgLLSdzX2/view?usp=sharing) | [**Read Problem PDF ↗**](https://drive.google.com/file/d/1qbH1IhaJLFGAXX505xwmFDKeSGzLrF4M/view?usp=sharing) |

[🚀 Quickstart](#-quickstart-5-steps) · [🏗️ Architecture](#️-architecture) · [📊 Scoring](#-scoring-metrics) · [🔄 Data Flow](#-data-flow) · [📁 Project Structure](#-project-structure) · [🎥 Demo](#-demo)

</div>

---

## 🎯 What Is This?

The **Persistent Context Engine** is a Python-based operational memory engine that gives your infrastructure a long-term memory. When an incident fires, it reconstructs full investigation context in **under 2 seconds** — including causal chain, similar past incidents, and ranked remediation suggestions.

It's **not** a dashboard. **Not** a log viewer. **Not** a search wrapper.

It is an engine that *remembers* — across renames, topology drift, and time.

```
📥 Events In  →  🧠 Memory Built  →  🔍 Incident Fires  →  📋 Context Out (< 2s)
```

### ✨ Key Differentiators

| Feature | Baseline | This Engine |
|---------|----------|-------------|
| Topology rename survival | ❌ Breaks on rename | ✅ Alias registry + transitive resolution |
| Fingerprinting | Service-name dependent | ✅ Topology-independent behavioral vectors |
| Context reconstruction | Naive similarity | ✅ Graph traversal + ChromaDB + Gemini |
| Causal chain | ❌ Not tracked | ✅ NetworkX causal graph with timestamps |
| Remediation ranking | None | ✅ Historical outcome reinforcement |

---

## 🚀 Quickstart (5 Steps)

### Prerequisites

- 🐳 Docker installed
- 🔑 Gemini API key ([get one free](https://aistudio.google.com/))

---

### Step 1 — Clone & Configure

```bash
git clone https://github.com/your-team/persistent-context-engine.git
cd persistent-context-engine

cp .env.example .env
# Open .env and set your Gemini API key:
# GEMINI_API_KEY=your_gemini_api_key_here
```

---

### Step 2 — Build the Docker Image

```bash
docker build -t persistent-context-engine .
```

> ⏱️ First build takes ~2 minutes. Subsequent builds use cached layers.

---

### Step 3 — Run the Engine

```bash
docker run --env-file .env \
  -v $(pwd)/data:/app/data \
  persistent-context-engine
```

Or using Docker Compose (recommended):

```bash
docker-compose up
```

---

### Step 4 — Ingest Sample Events

```bash
# Inside container or via docker exec:
python demo/scenario_runner.py --events demo/sample_events.jsonl
```

Expected output:
```
✅ Ingested 7 events
✅ Alias registry updated: payments-svc → billing-svc
✅ Causal graph: 6 nodes, 9 edges
✅ ChromaDB: 3 fingerprints stored
```

---

### Step 5 — Run the Benchmark

```bash
bash bench/run.sh
# Outputs: bench/report.json
```

```json
{
  "precision_at_5": 0.87,
  "recall_at_5": 0.91,
  "remediation_acc": 0.83,
  "latency_p95_fast_ms": 1420,
  "latency_p95_deep_ms": 4980,
  "pattern_f1": 0.89,
  "temporal_pct": 0.94,
  "delta_adaptability": 0.91
}
```

---

## 🏗️ Architecture

The engine is organized in three layers:

```
┌─────────────────────────────────────────────────────────────────┐
│                     LAYER 3: RECONSTRUCTION                      │
│   context_builder.py  →  event_ranker.py  →  gemini_client.py   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    LAYER 2: MEMORY & FINGERPRINTING              │
│   fingerprint.py  →  vector_store.py  →  incident_memory.py     │
│   causal_graph.py  →  alias_registry.py                         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    LAYER 1: INGEST & STORAGE                     │
│   pipeline.py  →  handlers.py  →  event_store.py (DuckDB)       │
│   buffer.py (flush every 2s)                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 🔑 The Two Public Methods

Everything in this project boils down to exactly two methods:

```python
from adapters.myteam import MyTeamAdapter

adapter = MyTeamAdapter()

# METHOD 1: Ingest a stream of telemetry events
adapter.ingest(events: Iterable[Event]) -> None

# METHOD 2: Reconstruct context at incident time
context = adapter.reconstruct_context(signal: IncidentSignal, mode="fast") -> Context
```

### 📋 Output Shape

```python
class Context(TypedDict):
    related_events:         list[Event]         # ordered, deduped, with provenance
    causal_chain:           list[CausalEdge]    # (cause_id, effect_id, evidence, confidence)
    similar_past_incidents: list[IncidentMatch] # (past_incident_id, similarity, rationale)
    suggested_remediations: list[Remediation]   # (action, target, historical_outcome, confidence)
    confidence:             float               # 0.0 to 1.0
    explain:                str                 # human-readable narrative (Gemini-generated)
```

---

## 🔄 Data Flow

```
1.  📨 Events arrive as JSONL stream
            ↓
2.  🔍 pipeline.py parses and validates each event
            ↓
3.  🔀 handlers.py routes by event.kind:
        deploy / log / metric / trace  →  event_store.py + graph_builder.py
        topology rename                →  alias_registry.py (merge nodes)
        incident_signal                →  incident_memory.py (start tracking)
        remediation                    →  incident_memory.py + remediation_ranker.py
            ↓
4.  🧬 fingerprint.py continuously updates behavioral fingerprints
            ↓
5.  🗃️  vector_store.py stores fingerprints in ChromaDB
            ↓
    ═══════════ INCIDENT FIRES ═══════════
            ↓
6.  🎯 context_builder.py called with IncidentSignal
            ↓
7.  🏷️  alias_registry.py resolves service name → canonical name
            ↓
8.  📅 event_store.py fetches events in ±10 min window
            ↓
9.  🕸️  causal_graph.py traverses edges → causal_chain
            ↓
10. 🔎 vector_store.py finds similar past fingerprints
            ↓
11. 💊 remediation_ranker.py ranks fixes by historical success
            ↓
12. ✨ [DEEP MODE ONLY] gemini_client.py generates explain narrative
            ↓
13. 📤 Returns Context TypedDict to adapter
```

---

## 🛡️ The Rename Problem — Solved

When a topology rename event arrives:

```json
{
  "kind": "topology",
  "change": "rename",
  "from": "payments-svc",
  "to": "billing-svc"
}
```

The engine performs **three simultaneous operations**:

```
┌─────────────────────────────────────────────────────────┐
│  1. ALIAS REGISTRY                                       │
│     billing-svc → payments-svc  (canonical)             │
│     pay-api → payments-svc      (transitive resolved)   │
├─────────────────────────────────────────────────────────┤
│  2. GRAPH MERGE                                          │
│     Merge billing-svc node INTO payments-svc node        │
│     All edges preserved on canonical node                │
├─────────────────────────────────────────────────────────┤
│  3. FINGERPRINT INDEPENDENCE                             │
│     "payments-svc had deploy" → "SERVICE_A had deploy"  │
│     billing-svc deploy == payments-svc deploy (match!)  │
└─────────────────────────────────────────────────────────┘
```

**Result:** A `billing-svc` incident correctly matches past `payments-svc` incidents with **zero manual intervention**.

---

## 📊 Scoring Metrics

| Metric | Target | Strategy |
|--------|--------|----------|
| 🎯 `precision@5` | ≥ 0.85 | ChromaDB cosine similarity on behavioral fingerprints |
| 📥 `recall@5` | ≥ 0.85 | Alias-resolved graph traversal catches renamed services |
| 💊 `remediation_acc` | ≥ 0.80 | Reinforcement learning from past `remediation` outcomes |
| ⚡ `latency_p95` fast | ≤ 2000ms | Pre-computed fingerprints, in-memory graph cache |
| ⚡ `latency_p95` deep | ≤ 6000ms | Full Gemini call + deeper traversal |
| 🧬 `pattern F1` | ≥ 0.87 | Topology-independent fingerprinting |
| ⏱️ `temporal %` | ≥ 0.90 | Timestamp-sorted edge insertion |
| 🔀 `Δ-adaptability` | ≥ 0.88 | Alias registry + transitive chain resolution |
| 📝 `explain grade` | A/B | Gemini 1.5 Flash/Pro narrative generation |

---

## 📁 Project Structure

```
persistent-context-engine/
│
├── 📄 README.md                    ← You are here
├── 📋 PRD.md                       ← Product requirements document
├── 🐳 Dockerfile                   ← Reproducible container
├── 🐳 docker-compose.yml           ← Multi-service orchestration
├── 📦 requirements.txt             ← All deps with version pins
├── 🔑 .env.example                 ← GEMINI_API_KEY=your_key_here
│
├── 📊 bench/
│   └── run.sh                      ← Runs benchmark, emits report.json
│
├── 🔌 adapters/
│   └── myteam.py                   ← Harness interface (ingest + reconstruct)
│
├── ⚙️  engine/                      ← Core engine — all business logic
│   ├── core.py                     ← MemorySubstrate — main coordinator
│   │
│   ├── 📥 ingestion/
│   │   ├── pipeline.py             ← Parses, validates, routes by event.kind
│   │   ├── handlers.py             ← Per-kind: deploy/log/metric/trace/topology
│   │   └── buffer.py               ← In-memory batch buffer (flush every 2s)
│   │
│   ├── 🗄️  storage/
│   │   ├── event_store.py          ← DuckDB: store/query/replay events
│   │   └── schema.sql              ← DuckDB table definitions
│   │
│   ├── 🕸️  graph/
│   │   ├── causal_graph.py         ← NetworkX DiGraph: add/traverse/chain
│   │   ├── alias_registry.py       ← 🔑 Rename handler (transitive resolution)
│   │   └── graph_builder.py        ← Builds edges from ingested events
│   │
│   ├── 🧠 memory/
│   │   ├── fingerprint.py          ← 🔑 Topology-independent behavioral vectors
│   │   ├── vector_store.py         ← ChromaDB: store/find similar fingerprints
│   │   └── incident_memory.py      ← Long-term rename-robust incident memory
│   │
│   ├── 🔍 reconstruction/
│   │   ├── context_builder.py      ← Orchestrates graph + memory + LLM
│   │   ├── event_ranker.py         ← Signal density ranking, noise filtering
│   │   └── remediation_ranker.py   ← Historical outcome reinforcement ranking
│   │
│   └── 🤖 llm/
│       ├── gemini_client.py        ← Gemini API (retry + timeout handling)
│       └── prompts.py              ← EXPLAIN / CAUSAL_CHAIN / REMEDIATION prompts
│
├── 🎬 demo/
│   ├── app.py                      ← Streamlit UI (demo video only)
│   ├── sample_events.jsonl         ← 7 sample events from problem statement
│   └── scenario_runner.py          ← Feeds events into engine for demo
│
└── 🧪 tests/
    ├── test_alias_registry.py      ← Rename chain resolution tests
    ├── test_fingerprint.py         ← Behavioral fingerprint unit tests
    ├── test_ingest.py              ← Ingestion pipeline unit tests
    └── test_reconstruct.py         ← Full reconstruction integration test
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Optional — defaults shown
CHROMA_PERSIST_DIR=./data/chroma
DUCKDB_PATH=./data/events.db
LOG_LEVEL=INFO
FAST_MODE_TIMEOUT_S=1.8
DEEP_MODE_TIMEOUT_S=5.5
```

---

## 📡 Supported Event Types

| Kind | Key Fields | Description |
|------|-----------|-------------|
| `deploy` | service, version, actor | Code deployed to a service |
| `log` | service, level, msg, trace_id | A log line emitted |
| `metric` | service, name, value | A metric value recorded |
| `trace` | trace_id, spans[{svc, dur_ms}] | A distributed trace |
| `topology` | change, from, to | Service renamed or dependency changed |
| `incident_signal` | incident_id, trigger | An alert fired |
| `remediation` | incident_id, action, target, version, outcome | A fix was applied |

---

## ⚡ Performance Targets

| Operation | Target | Mechanism |
|-----------|--------|-----------|
| Ingest throughput | ≥ 1,000 events/sec | Batch inserts, async graph updates |
| Ingest lag | ≤ 5 seconds | In-memory buffer, flush every 2s |
| `reconstruct` fast mode | p95 ≤ 2s | Pre-computed fingerprints + cached graph |
| `reconstruct` deep mode | p95 ≤ 6s | Full Gemini call + deeper traversal |
| Cold start | ≤ 60s | Lazy loading, DuckDB persistence |

---

## 🧪 Running Tests

```bash
# Unit tests
pytest tests/test_alias_registry.py -v
pytest tests/test_fingerprint.py -v
pytest tests/test_ingest.py -v

# Integration test
pytest tests/test_reconstruct.py -v

# All tests
pytest tests/ -v --tb=short
```

---

## 🎥 Demo

### 🌐 Live Deployed App

> **The engine is live and running on Railway:**
> ### 👉 [context-engine-code-lunatics-production.up.railway.app](https://context-engine-code-lunatics-production.up.railway.app/)

---

### 📹 Demo Video

> **Watch the full 5-minute walkthrough:**
> ### 👉 [Watch on Google Drive](https://drive.google.com/file/d/1j2_MdsQ70vj6eN5-1xolbKCWgLLSdzX2/view?usp=sharing)

The demo covers:
- 📨 Live event ingestion from the sample JSONL
- 🕸️ Memory graph building in real-time
- 🔀 Alias registry updating on rename event
- 🔍 `reconstruct_context()` running on INC-714
- 📋 Full output: causal chain + similar incidents + remediations

---

### 🖥️ Run Locally (Streamlit UI)

```bash
streamlit run demo/app.py
```

> The local Streamlit UI is for development/demo purposes only and is not judged.

---

## 🏗️ Tech Stack Decisions

| Component | Tool | Why |
|-----------|------|-----|
| 🐍 Core language | Python 3.11 | Required by harness |
| 🗄️ Event storage | DuckDB (in-process) | 1000+ events/sec, columnar, no server |
| 🕸️ Causal graph | NetworkX | Pure Python, instant startup, no server |
| 🔎 Vector similarity | ChromaDB | Local vector store, fully in-process |
| 🤖 LLM reasoning | Gemini 1.5 Flash/Pro | Fast, cost-effective, strong reasoning |
| 🎬 Demo UI | Streamlit | Zero-config Python UI |
| 🐳 Container | Docker | Reproducible submissions |

---

## 🚧 Build Order (For Contributors)

Build in this exact order — each step is independently testable:

```
Step 1  →  schema.py alignment         TypedDicts must match harness exactly
Step 2  →  event_store.py              DuckDB setup and event queries
Step 3  →  alias_registry.py           Rename handling (most critical)
Step 4  →  pipeline.py + handlers.py   End-to-end ingest pipeline
Step 5  →  causal_graph.py             Build graph from events
Step 6  →  fingerprint.py              Topology-independent signatures
Step 7  →  vector_store.py             ChromaDB integration
Step 8  →  incident_memory.py          Connect fingerprints to incidents
Step 9  →  context_builder.py          Wire everything together
Step 10 →  gemini_client.py            Add LLM for explain field
Step 11 →  adapters/myteam.py          Wire to harness interface
Step 12 →  self_check.py run           Iterate on weak metrics
Step 13 →  demo/app.py                 Streamlit UI for demo video
Step 14 →  Dockerfile + README         Submission packaging
```

---

## 🔒 Submission Checklist

- [x] `adapters/myteam.py` — implements `ingest()` and `reconstruct_context()`
- [x] `bench/run.sh` — runs benchmark, emits `report.json`
- [x] `Dockerfile` — reproducible environment
- [x] `README.md` — quickstart in 5 steps
- [x] `requirements.txt` — all deps with version pins
- [x] 5-min demo video — [Watch on Google Drive](https://drive.google.com/file/d/1j2_MdsQ70vj6eN5-1xolbKCWgLLSdzX2/view?usp=sharing)
- [x] Deployed live — [context-engine-code-lunatics-production.up.railway.app](https://context-engine-code-lunatics-production.up.railway.app/)
- [ ] 3-page PDF writeup

---

## ⚠️ Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Gemini API exceeds 2s budget | Cache calls; fast mode skips Gemini entirely |
| ChromaDB cold start latency | Pre-load on `__init__`, persist to disk |
| Rename chain `A→B→C` breaks resolution | Full transitive resolution in alias registry |
| Graph too large for memory | Prune edges older than 30 days; keep incident nodes forever |
| Wildly different benchmark seeds | All logic is pattern-based, zero hardcoding |

---

## 📎 Resources & Links

| Resource | Link |
|----------|------|
| 🌐 **Live Deployed App** | [context-engine-code-lunatics-production.up.railway.app](https://context-engine-code-lunatics-production.up.railway.app/) |
| 🎥 **Demo Video** | [Watch on Google Drive](https://drive.google.com/file/d/1j2_MdsQ70vj6eN5-1xolbKCWgLLSdzX2/view?usp=sharing) |
| 📄 **Problem Statement PDF** | [View on Google Drive](https://drive.google.com/file/d/1qbH1IhaJLFGAXX505xwmFDKeSGzLrF4M/view?usp=sharing) |
| 🤖 **Gemini API** | [aistudio.google.com](https://aistudio.google.com/) |
| 🗄️ **DuckDB Docs** | [duckdb.org](https://duckdb.org/) |
| 🔎 **ChromaDB Docs** | [trychroma.com](https://www.trychroma.com/) |
🔎 **Benchmark Output Score matrix ** | [View Output on drive](https://drive.google.com/file/d/1gaxiuBj6HxF785vI49THFcaEPfuYJyMQ/view?usp=sharing)
**Benchmark Output Reconstructed matrix ** | [View Output on drive](https://drive.google.com/file/d/1oDVY6I7sg_CtBLSqS9g23tFesfcObyGV/view?usp=sharing)


---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

Built with ❤️ for the **Anvil Hackathon** · Problem 02/04

*"The best ops teams don't just fight fires — they remember every fire they've ever fought."*

</div>
