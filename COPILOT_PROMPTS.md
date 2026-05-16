# GitHub Copilot Prompts — Persistent Context Engine
## Paste each prompt into Copilot Chat when working on that file

---

## PROMPT 0 — Project Context (Paste this FIRST in every new Copilot session)

```
I am building a Persistent Context Engine for an SRE hackathon.
It is a Python operational memory engine with exactly two public methods:

1. ingest(events) — consumes a stream of infrastructure telemetry events
2. reconstruct_context(signal, mode) — returns structured incident context

The engine must handle topology drift — if service "payments-svc" is renamed
to "billing-svc", it must still match the same failure patterns across the rename.

Tech stack:
- Python 3.11
- DuckDB for event storage (in-process, no server)
- NetworkX for causal graph (in-memory)
- ChromaDB for vector similarity (in-process, persists to disk)
- Gemini 1.5 Flash API for LLM reasoning (key in env GEMINI_API_KEY)

The output Context TypedDict must have these exact fields:
  related_events: list[Event]
  causal_chain: list[CausalEdge]
  similar_past_incidents: list[IncidentMatch]
  suggested_remediations: list[Remediation]
  confidence: float
  explain: str

Keep all code production-quality with type hints and docstrings.
```

---

## PROMPT 1 — DuckDB Event Store (`engine/storage/event_store.py`)

```
Create engine/storage/event_store.py

This is a DuckDB-based event store for infrastructure telemetry.

Requirements:
- Use duckdb Python library, in-process database (no server)
- Database file path comes from env var DUCKDB_PATH, default ./data/events.db
- Create this table on init if not exists:
    CREATE TABLE events (
      id VARCHAR PRIMARY KEY,
      ts TIMESTAMP,
      kind VARCHAR,
      service VARCHAR,
      data JSON,
      ingested_at TIMESTAMP DEFAULT now()
    )
- Methods needed:
    store_event(event: dict) -> None
      - Generates id as uuid4 if not present
      - Stores full event as JSON in data column
      
    store_events_batch(events: list[dict]) -> None  
      - Bulk insert for performance, must handle 1000+ events/sec
      
    query_time_window(service: str, ts: datetime, window_minutes: int = 10) -> list[dict]
      - Returns all events for a service within ±window_minutes of ts
      - Resolves aliases: accepts a list of alias names to query
      
    get_events_by_incident(incident_id: str) -> list[dict]
      - Returns all events associated with an incident_id
      
    get_recent_deploys(service: str, limit: int = 5) -> list[dict]
      - Returns most recent deploy events for a service
      
    close() -> None
      - Closes DuckDB connection

Use connection pooling pattern. Handle concurrent access safely.
Add docstrings to every method explaining what it does.
```

---

## PROMPT 2 — Alias Registry (`engine/graph/alias_registry.py`)

```
Create engine/graph/alias_registry.py

This is THE most critical file in the project. It handles service renames
so that "billing-svc" and "payments-svc" are treated as the same service
even after a topology rename event.

Requirements:
- Class AliasRegistry with these methods:

    register_rename(from_name: str, to_name: str, ts: datetime) -> None
      - Records that from_name was renamed to to_name at timestamp ts
      - Must handle CHAINS: if A→B then B→C, resolve(C) should return A
      - Stores rename history with timestamps for temporal reasoning
      
    resolve(name: str) -> str
      - Returns the canonical (original) name for any alias
      - If "billing-svc" was renamed from "payments-svc", resolve("billing-svc") returns "payments-svc"
      - If name is already canonical, returns it unchanged
      
    get_all_aliases(canonical: str) -> list[str]
      - Returns all known names for a canonical service
      - e.g. get_all_aliases("payments-svc") returns ["payments-svc", "billing-svc"]
      
    resolve_event(event: dict) -> dict
      - Takes an event dict, resolves any service name fields to canonical names
      - Returns a new event dict with resolved names, preserving original in _original_service field
      
    get_rename_history(service: str) -> list[dict]
      - Returns list of {from, to, ts} rename events for a service
      
    is_same_service(name_a: str, name_b: str) -> bool
      - Returns True if both names resolve to the same canonical name

- Internal storage: use a dict for forward mapping and a dict for reverse mapping
- Must be thread-safe (use threading.Lock)
- Add full docstrings with examples

Example usage:
  registry = AliasRegistry()
  registry.register_rename("payments-svc", "billing-svc", ts)
  registry.resolve("billing-svc")  # returns "payments-svc"
  registry.is_same_service("payments-svc", "billing-svc")  # returns True
```

---

## PROMPT 3 — Ingestion Pipeline (`engine/ingestion/pipeline.py` and `handlers.py`)

```
Create engine/ingestion/pipeline.py and engine/ingestion/handlers.py

The pipeline is the entry point for all telemetry events.

pipeline.py — class IngestionPipeline:
    __init__(self, event_store, graph_builder, alias_registry, incident_memory)
    
    consume(self, event: dict) -> None
      - Validates event has required fields: ts, kind
      - Converts ts string to datetime
      - Routes to correct handler based on event.kind
      - Handles unknown kinds gracefully (log warning, don't crash)
      
    consume_batch(self, events: list[dict]) -> None
      - Processes a batch of events efficiently
      - Uses batch insert for DuckDB
      
handlers.py — one function per event kind:

    handle_deploy(event, event_store, graph_builder, incident_memory) -> None
      - Store event in DuckDB
      - Add deploy node to causal graph
      - Tag as potential incident trigger (deploys often cause incidents)
      
    handle_log(event, event_store, graph_builder) -> None
      - Store event in DuckDB
      - If level == "error" or "critical": add to causal graph as error node
      - Extract trace_id if present, link to trace events
      
    handle_metric(event, event_store, graph_builder) -> None
      - Store event in DuckDB
      - Detect anomalies: if latency_p99_ms > 2000, flag as spike
      - If spike detected, add anomaly edge to causal graph
      
    handle_trace(event, event_store, graph_builder) -> None
      - Store event in DuckDB
      - For each span: create service dependency edge in graph
      - Link spans with high dur_ms (> 1000) as latency nodes
      
    handle_topology(event, event_store, alias_registry, graph_builder) -> None
      - Store event in DuckDB
      - If change == "rename": call alias_registry.register_rename()
      - Merge graph nodes for old and new service name
      
    handle_incident_signal(event, event_store, incident_memory) -> None
      - Store event in DuckDB
      - Start tracking this incident_id in incident_memory
      - Record trigger and timestamp
      
    handle_remediation(event, event_store, incident_memory) -> None
      - Store event in DuckDB
      - Record remediation outcome in incident_memory
      - If outcome == "resolved": reinforce this remediation pathway

All handlers must be pure functions (no side effects beyond their stated purpose).
Add type hints and docstrings.
```

---

## PROMPT 4 — Causal Graph (`engine/graph/causal_graph.py`)

```
Create engine/graph/causal_graph.py

A NetworkX DiGraph that stores causal relationships between events.

Class CausalGraph:

    __init__(self)
      - Initialise a networkx.DiGraph
      - Thread-safe with threading.RLock
      
    add_event_node(event_id: str, event: dict) -> None
      - Add a node for this event
      - Node attributes: kind, service, ts, data
      
    add_causal_edge(cause_id: str, effect_id: str, evidence: str, confidence: float) -> None
      - Add directed edge from cause to effect
      - Edge attributes: evidence (why we think this caused that), confidence (0.0-1.0), ts
      
    get_causal_chain(incident_id: str, max_depth: int = 5) -> list[dict]
      - Starting from events near the incident signal time, traverse backwards
      - Return list of CausalEdge dicts:
        {cause_id, effect_id, evidence, confidence}
      - Only include edges with confidence >= 0.3
      - Order from root cause to effect (earliest to latest)
      
    get_related_events(service: str, ts: datetime, window_minutes: int = 10) -> list[str]
      - Returns event IDs of nodes connected (directly or via 1 hop) to service
      - Within the time window
      
    merge_service_nodes(old_service: str, new_service: str) -> None
      - Called when a rename happens
      - Rewire all edges from old_service nodes to point to new_service canonical
      - Preserve all historical edges

Causal edge inference rules (implement these):
  Rule 1: deploy event BEFORE metric spike (within 5 min) → add edge deploy→spike, confidence 0.7
  Rule 2: metric spike BEFORE log error (within 2 min) → add edge spike→error, confidence 0.8
  Rule 3: log error with trace_id matches trace span → add edge error→trace, confidence 0.9
  Rule 4: incident_signal AFTER log error (within 5 min, same service) → add edge error→incident, confidence 0.85

Add docstrings with examples.
```

---

## PROMPT 5 — Behavioral Fingerprinting (`engine/memory/fingerprint.py`)

```
Create engine/memory/fingerprint.py

This is the second most critical file. It creates topology-independent
behavioral fingerprints of incidents so they can be matched across
service renames.

KEY INSIGHT: The fingerprint must NOT contain service names.
It must capture the PATTERN of what happened, not WHICH services.

Class BehavioralFingerprint (TypedDict):
    pattern_sequence: list[str]    # e.g. ["deploy", "latency_spike", "upstream_error"]
    trigger_type: str              # e.g. "error_rate", "latency", "availability"
    severity: str                  # "low", "medium", "high", "critical"
    time_to_trigger_mins: float    # How long from first signal to incident
    has_deploy_precursor: bool     # Was there a recent deploy?
    has_latency_spike: bool        # Was there a latency spike?
    has_upstream_errors: bool      # Were there upstream service errors?
    has_trace_anomaly: bool        # Were there slow traces?
    remediation_type: str | None   # "rollback", "restart", "scale", "config_change", None
    resolution_time_mins: float | None

Class FingerprintExtractor:

    extract(
        incident_id: str,
        incident_event: dict,
        related_events: list[dict],
        remediation: dict | None = None
    ) -> BehavioralFingerprint
      - Takes an incident and its context
      - Returns a topology-independent fingerprint
      - MUST NOT include service names in the fingerprint
      
    to_vector(fingerprint: BehavioralFingerprint) -> list[float]
      - Converts fingerprint to a fixed-length float vector for ChromaDB
      - Vector length: 20 dimensions
      - Encode pattern_sequence as one-hot or frequency features
      
    to_text(fingerprint: BehavioralFingerprint) -> str
      - Converts fingerprint to a text description for embedding
      - Used as ChromaDB document text
      - Example: "deploy precursor, latency spike, upstream errors, rollback resolved"
      
    similarity(fp1: BehavioralFingerprint, fp2: BehavioralFingerprint) -> float
      - Compute similarity between two fingerprints (0.0-1.0)
      - Use cosine similarity on to_vector() output

Add full docstrings and a simple test at the bottom:
if __name__ == "__main__":
    # show example fingerprint extraction and similarity
```

---

## PROMPT 6 — Vector Store (`engine/memory/vector_store.py`)

```
Create engine/memory/vector_store.py

ChromaDB wrapper for storing and querying behavioral fingerprints.
Must run fully in-process (no separate Chroma server).

Class VectorStore:

    __init__(self, persist_dir: str = "./data/chroma")
      - Initialise chromadb.PersistentClient with persist_dir
      - Create or get collection named "incident_fingerprints"
      - Collection uses cosine distance
      
    store_fingerprint(
        incident_id: str,
        fingerprint_text: str,
        fingerprint_vector: list[float],
        metadata: dict
    ) -> None
      - Store fingerprint in ChromaDB
      - metadata should include: service (canonical), ts, remediation_type, outcome
      - Use incident_id as document ID (upsert — overwrite if exists)
      
    find_similar(
        query_text: str,
        query_vector: list[float],
        n_results: int = 5,
        exclude_incident_id: str | None = None
    ) -> list[dict]
      - Query ChromaDB for most similar past incidents
      - Returns list of dicts with: incident_id, similarity, metadata
      - similarity is 1.0 - distance (cosine)
      - Exclude the current incident if exclude_incident_id is provided
      
    get_by_incident_id(incident_id: str) -> dict | None
      - Retrieve a stored fingerprint by incident ID
      
    count(self) -> int
      - Returns total number of stored fingerprints

Use chromadb library. Handle the case where ChromaDB collection is empty gracefully.
All methods should handle exceptions and log errors without crashing.
```

---

## PROMPT 7 — Incident Memory (`engine/memory/incident_memory.py`)

```
Create engine/memory/incident_memory.py

Connects incidents to their fingerprints, tracks outcomes, enables
similarity-based recall.

Class IncidentMemory:

    __init__(self, vector_store: VectorStore, fingerprint_extractor: FingerprintExtractor, alias_registry: AliasRegistry)
    
    remember_incident(
        incident_id: str,
        incident_event: dict,
        related_events: list[dict]
    ) -> None
      - Called when an incident_signal arrives
      - Extracts fingerprint from incident + related events
      - Stores in vector_store
      - Also stores in internal dict for fast lookup
      
    record_remediation(
        incident_id: str,
        remediation_event: dict
    ) -> None
      - Called when a remediation event arrives
      - Updates the stored fingerprint with remediation info
      - If outcome == "resolved": boost confidence of this remediation type
      
    recall_similar(
        incident_event: dict,
        related_events: list[dict],
        n: int = 5
    ) -> list[dict]
      - Find historically similar incidents
      - Returns list of IncidentMatch dicts:
        {past_incident_id, similarity, rationale}
      - rationale should be human-readable: "Similar deploy→latency→error pattern,
        resolved by rollback"
      - Uses alias_registry to resolve service names before fingerprinting
      - This is the RENAME-ROBUST recall — must work across topology changes
      
    get_successful_remediations(
        incident_id: str,
        similar_incidents: list[dict]
    ) -> list[dict]
      - From similar incidents, extract what remediations were successful
      - Returns list of Remediation dicts:
        {action, target, historical_outcome, confidence}
      - confidence = (count of successful uses) / (total uses)

This class is what makes the engine "remember" across renames.
Docstrings must include examples of rename-robust recall.
```

---

## PROMPT 8 — Context Builder (`engine/reconstruction/context_builder.py`)

```
Create engine/reconstruction/context_builder.py

The orchestrator for reconstruct_context(). Pulls together all subsystems
and returns the final Context TypedDict.

Class ContextBuilder:

    __init__(self, event_store, causal_graph, incident_memory, alias_registry, gemini_client)
    
    build(
        signal: dict,  # IncidentSignal
        mode: str = "fast"
    ) -> dict:  # Context TypedDict
      
      This is the main method. It must complete in:
        - fast mode: p95 ≤ 2 seconds (NO Gemini call in fast mode if too slow)
        - deep mode: p95 ≤ 6 seconds (use Gemini for better explain)
      
      Steps:
      1. Resolve service name via alias_registry
      2. Parse timestamp from signal
      3. Query event_store for events in ±10 min window → related_events
      4. Get causal_chain from causal_graph (max_depth=3 for fast, 5 for deep)
      5. Call incident_memory.recall_similar() → similar_past_incidents
      6. Call incident_memory.get_successful_remediations() → suggested_remediations
      7. Compute overall confidence (average of causal edge confidences)
      8. Generate explain field:
           - fast mode: build explain from template (no LLM)
           - deep mode: call gemini_client.generate_explanation()
      9. Return Context dict with all fields populated
      
      Fallback: if any step fails, return partial Context with what we have.
      Never crash — always return something.

    _build_fast_explanation(
        signal: dict,
        related_events: list,
        causal_chain: list,
        similar_incidents: list,
        remediations: list
    ) -> str
      - Template-based explanation for fast mode
      - Example: "checkout-api error rate exceeded 5% at 14:32. 
        Root cause: billing-svc (formerly payments-svc) deployed v2.14.0 
        11 minutes prior, causing p99 latency spike to 4820ms. 
        Matches INC-201 pattern (similarity: 0.91). 
        Suggested action: rollback to previous version."

Add comprehensive error handling and timing logs.
```

---

## PROMPT 9 — Gemini Client (`engine/llm/gemini_client.py` and `prompts.py`)

```
Create engine/llm/gemini_client.py and engine/llm/prompts.py

Gemini API wrapper for generating explanations and enhancing causal chains.

gemini_client.py — Class GeminiClient:

    __init__(self, api_key: str | None = None, timeout_s: float = 5.0)
      - api_key from parameter or GEMINI_API_KEY env var
      - Use google-generativeai library
      - Model: gemini-1.5-flash (fast) for fast mode
      - Model: gemini-1.5-pro for deep mode

    generate_explanation(
        signal: dict,
        related_events: list[dict],
        causal_chain: list[dict],
        similar_incidents: list[dict],
        suggested_remediations: list[dict]
    ) -> str
      - Calls Gemini with EXPLAIN_PROMPT
      - Returns human-readable narrative for the explain field
      - Must complete within timeout_s
      - On timeout or error: return fallback template string

    enhance_causal_chain(
        events: list[dict],
        existing_chain: list[dict]
    ) -> list[dict]
      - [DEEP MODE ONLY] Ask Gemini to find additional causal edges
      - Returns enhanced causal_chain list
      - On error: return existing_chain unchanged

    is_available(self) -> bool
      - Returns True if API key is set and Gemini is reachable

prompts.py — prompt templates as constants:

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
    
    Also create CAUSAL_CHAIN_PROMPT for enhance_causal_chain().
    
Use google-generativeai>=0.7.0. Handle rate limits with exponential backoff (max 2 retries).
```

---

## PROMPT 10 — Core Engine (`engine/core.py`)

```
Create engine/core.py

The MemorySubstrate — coordinates all subsystems. This is instantiated
once and lives for the lifetime of the engine.

Class MemorySubstrate:

    __init__(self)
      - Initialise all subsystems in correct dependency order:
        1. alias_registry = AliasRegistry()
        2. event_store = EventStore()
        3. causal_graph = CausalGraph()
        4. fingerprint_extractor = FingerprintExtractor()
        5. vector_store = VectorStore()
        6. incident_memory = IncidentMemory(vector_store, fingerprint_extractor, alias_registry)
        7. pipeline = IngestionPipeline(event_store, causal_graph, alias_registry, incident_memory)
        8. gemini_client = GeminiClient()
        9. context_builder = ContextBuilder(event_store, causal_graph, incident_memory, alias_registry, gemini_client)
      - Log "MemorySubstrate initialized" with subsystem status
      
    consume(self, event: dict) -> None
      - Calls pipeline.consume(event)
      - Thread-safe
      
    consume_batch(self, events: list[dict]) -> None
      - Calls pipeline.consume_batch(events)
      - This is the performance-critical path: must sustain 1000 events/sec
      
    reconstruct(self, signal: dict, mode: str = "fast") -> dict
      - Calls context_builder.build(signal, mode)
      - Returns Context TypedDict
      
    shutdown(self) -> None
      - Gracefully close event_store, vector_store
      - Flush any pending buffer

Import all subsystems. Log timing for each consume_batch call.
```

---

## PROMPT 11 — Adapter (`adapters/myteam.py`)

```
Create adapters/myteam.py

This is the ONLY file the benchmark harness calls. It must implement
the Adapter base class exactly.

from adapter import Adapter
from schema import Event, IncidentSignal, Context
from engine.core import MemorySubstrate

class Engine(Adapter):

    def __init__(self):
        """Initialise the memory substrate."""
        self.store = MemorySubstrate()
    
    def ingest(self, events) -> None:
        """
        Consume a stream of telemetry events.
        Called with an iterable of Event dicts.
        Must handle 1000+ events/sec.
        """
        events_list = list(events)
        if events_list:
            self.store.consume_batch(events_list)
    
    def reconstruct_context(self, signal: IncidentSignal, mode: str = "fast") -> Context:
        """
        Reconstruct operational context for an incident signal.
        fast mode: p95 ≤ 2 seconds
        deep mode: p95 ≤ 6 seconds
        """
        return self.store.reconstruct(dict(signal), mode=mode)
    
    def close(self) -> None:
        """Shutdown gracefully."""
        self.store.shutdown()

Keep this file as thin as possible. All logic lives in engine/.
```

---

## PROMPT 12 — Streamlit Demo UI (`demo/app.py`)

```
Create demo/app.py

A Streamlit UI for the 5-minute demo video. This is NOT judged — it only
needs to look good on screen.

Screens/sections:

1. SIDEBAR: "Feed Events" section
   - File uploader for .jsonl files
   - OR a text area to paste JSON events
   - Button: "▶ Ingest Events"
   - Status: "✅ 7 events ingested | 4 graph nodes | 2 services tracked"

2. MAIN AREA — 4 tabs:

   Tab 1: "🚨 Trigger Incident"
   - Input: Incident ID (text input, default "INC-714")  
   - Input: Service (text input, default "billing-svc")
   - Input: Trigger (text input, default "alert:checkout-api/error-rate>5%")
   - Toggle: Fast mode / Deep mode
   - Button: "🔍 Reconstruct Context"
   
   Tab 2: "🧠 Reconstructed Context" (shows output)
   - Section: Causal Chain (show as visual flow: cause → effect with confidence %)
   - Section: Similar Past Incidents (show as table with similarity score)
   - Section: Suggested Remediations (show top recommendation highlighted)
   - Section: Explanation (show the explain field as a styled callout)
   - Overall confidence as a progress bar
   
   Tab 3: "🕸️ Memory Graph"
   - Show service nodes and their relationships
   - Use streamlit-agraph or pyvis for graph visualization
   - Highlight renamed services (show "billing-svc (was: payments-svc)")
   
   Tab 4: "📋 Raw Events"
   - Show all ingested events as a dataframe
   - Filter by kind (deploy, log, metric, etc.)

Use st.session_state to persist the engine across reruns.
Initialize engine once: if "engine" not in st.session_state: st.session_state.engine = Engine()

Make it visually clean. Use st.columns for layout. Add st.spinner for "Reconstructing context...".
```

---

## PROMPT 13 — Dockerfile

```
Create a Dockerfile for the Persistent Context Engine.

Requirements:
- Base image: python:3.11-slim
- Working directory: /app
- Copy requirements.txt and install dependencies
- Copy all source code
- Create data directory: /app/data (for DuckDB and ChromaDB persistence)
- Environment variables with defaults:
    GEMINI_API_KEY (required, no default)
    CHROMA_PERSIST_DIR=/app/data/chroma
    DUCKDB_PATH=/app/data/events.db
    LOG_LEVEL=INFO
- CMD should NOT run the app — judges run it themselves via bench/run.sh
- Add a HEALTHCHECK that imports the engine module

Also create requirements.txt with these packages and exact versions:
    duckdb==0.10.3
    networkx==3.3
    chromadb==0.5.0
    google-generativeai==0.7.2
    streamlit==1.35.0
    python-dotenv==1.0.1
    numpy==1.26.4

Make the Dockerfile production-quality. Multi-stage build not required for hackathon.
```

---

## PROMPT 14 — README

```
Create README.md for the Persistent Context Engine hackathon submission.

Include these sections:

# Persistent Context Engine

## Quickstart (5 steps)
1. Clone and navigate to repo
2. Copy .env.example to .env and add GEMINI_API_KEY
3. pip install -r requirements.txt
4. Run self-check: python self_check.py --adapter adapters.myteam:Engine --quick
5. Run full benchmark: python run.py --adapter adapters.myteam:Engine --mode fast --seeds 9999 31415

## Architecture
Brief description with ASCII diagram of the data flow

## Key Design Decisions
- Why topology-independent fingerprinting (the rename problem)
- Why DuckDB over SQLite
- Why NetworkX over Neo4j
- Why ChromaDB over Qdrant
- How fast mode achieves <2s without LLM

## How Rename-Robustness Works
Clear explanation with the payments-svc → billing-svc example

## Running the Demo UI
streamlit run demo/app.py

## Dependencies
Table of all deps with versions and purpose

## Environment Variables
Table of all env vars with defaults

Keep it concise — judges skim READMEs. Every section should be scannable.
```

---

## TIPS FOR USING THESE PROMPTS

1. **Always paste PROMPT 0 first** at the start of every Copilot session — it sets the context

2. **One prompt per file** — don't try to generate multiple files at once

3. **After generating each file**, immediately test it:
   ```bash
   python -c "from engine.storage.event_store import EventStore; e = EventStore(); print('OK')"
   ```

4. **If Copilot generates something wrong**, add to your prompt:
   > "The above is wrong because [reason]. Instead, [what you want]."

5. **Build order matters** — follow the order in PROJECT_STRUCTURE.md (event_store first, alias_registry second, etc.)

6. **For the alias_registry**, tell Copilot:
   > "The transitive chain resolution is the most important part. If A→B and B→C, then resolve(C) must return A. Make sure the test at the bottom proves this."

7. **For the fingerprint**, tell Copilot:
   > "Run this sanity check: create two fingerprints for the same pattern but different service names, and assert similarity > 0.9"
```
