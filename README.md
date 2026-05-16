# Persistent Context Engine — SRE Hackathon Submission

A production-quality Python operational memory engine that ingests infrastructure telemetry, builds causal relationships, and reconstructs incident context in under 2 seconds. **Handles topology drift transparently** via topology-independent behavioral fingerprinting.

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Create .env
```bash
cp .env.example .env
export GEMINI_API_KEY=your_key_here  # Optional for deep mode
```

### 3. Run Benchmark
```bash
python self_check.py --adapter adapters.myteam:TeamAdapter --mode fast --quick
```

## Architecture

Three-layer design:
- **Layer 1 (Storage)**: DuckDB for fast event queries + ingestion pipeline
- **Layer 2 (Memory)**: Alias registry for renames + fingerprinting for topology drift + ChromaDB for similarity
- **Layer 3 (Reconstruction)**: Causal graph traversal + LLM reasoning + ranking

### Key Differentiators

1. **Topology-Independent Fingerprinting** — Incidents survive service renames (payments-svc → billing-svc)
2. **Transitive Rename Resolution** — A→B→C chains resolve correctly
3. **Latency Budget Design** — Fast mode <2s, deep mode <6s with optional Gemini explanations

## File Structure

```
engine/
├── core.py                      # Main orchestrator (MemorySubstrate)
├── storage/event_store.py       # DuckDB persistence
├── graph/
│   ├── alias_registry.py        # CRITICAL: Rename handling
│   └── causal_graph.py          # NetworkX causal relationships
├── ingestion/
│   ├── pipeline.py              # Event validation + routing
│   └── handlers.py              # Kind-specific processing
├── memory/
│   ├── fingerprint.py           # CRITICAL: Topology-independent signatures
│   ├── vector_store.py          # ChromaDB integration
│   └── incident_memory.py       # Long-term storage
├── reconstruction/
│   ├── context_builder.py       # Reconstruction orchestrator
│   └── event_ranker.py          # Signal filtering
└── llm/gemini_client.py         # LLM explanations

adapters/myteam.py              # Harness interface
self_check.py     # condensed entry point for local iteration
adapters/
  dummy.py        # naive baseline; matches by exact service name only
```

## Anti-gaming · how the benchmark resists hardcoding

Three layers of evaluation. You see L1 and L2; you do not see L3.

**L1 — Worked example.** The single canonical trace from Annex A of the problem statement. Passes are necessary but not sufficient.

**L2 — Property-based multi-seed evaluation.** `--seeds` accepts ANY integers. The generator produces a fully deterministic dataset per seed: services, deploys, topology mutations, recurring incident families with morphed signatures. For an honest engine, **every** seed produces good metrics. A hardcoded lookup table fails for any seed it was not trained on.

The harness runs each seed in a **freshly constructed adapter**. State cannot leak between seeds. In-memory caches do not give a cross-seed signal.

Try arbitrary seeds locally:

```bash
python run.py --adapter adapters.mine:Engine \
  --seeds 9999 31415 27182 16180 11235 --n-services 20 --days 14
```

**L3 — Held-out adversarial scenarios.** The council holds:

- Private seeds at higher parameter values (more services, denser drift, more incident families per dataset).
- Hand-crafted scenarios that the generator alone does not produce — e.g., correlated multi-service outages, cascading rename chains, families whose signature is morphed across both rename and dependency-graph shifts.

L3 runs only at final evaluation. It is never distributed.

## Robustness · what the harness does to ensure clean numbers

- **Per-seed adapter instances.** Cached state, JIT caches, embedding stores — all reset per seed. Eliminates accidental cross-seed leakage as a confound.
- **Warmup queries.** First `--warmup N` queries per seed are discarded from latency aggregation. Cold-start effects do not poison p95.
- **p95 across the worst seed.** Latency budget is enforced against the worst-seed p95, not the mean. Tail behaviour matters.
- **Mean across seeds for quality metrics.** Random good luck on one seed does not inflate the score.

## Writing an adapter

Subclass `Adapter` in `adapters/<your_team>.py` and implement:

| Method | Purpose |
|---|---|
| `ingest(events)` | Consume an iterable of `Event` dicts |
| `reconstruct_context(signal, mode)` | Return a `Context` dict |
| `close()` | Tear down |

See `schema.py` for the exact `Event`, `IncidentSignal`, and `Context` shapes.

For non-Python engines, the adapter bridges via subprocess / gRPC / HTTP.

## Generator

`generator.py` produces a deterministic dataset with:

- **N services** with periodic background metrics (`qps`)
- **Deploys** across the time window
- **Topology mutations** — renames (the central test for drift), plus dependency add/remove
- **Incidents** drawn from **K recurring families**. Each incident is a pattern of (deploy → latency spike → upstream error → signal → remediation). Families repeat across the dataset with morphed signatures — when the involved service has been renamed, the same family looks superficially different.

Train / eval split: 70 / 30 by time. Eval signals are held out; the engine sees pre-signal context but not the remediation, which it must predict.

Defaults are small for fast local runs. Production scale is set by the council at event start via `--n-services`, `--days`, and generator config.

## Metrics

Computed per held-out incident, then aggregated:

| Metric | Definition |
|---|---|
| `recall@5` | Fraction of held-out incidents where a same-family training incident appears in the top-5 `similar_past_incidents` |
| `precision@5_mean` | Average precision of the top-5 `similar_past_incidents` across all held-out incidents |
| `remediation_acc` | Fraction of held-out incidents where the engine suggested the correct remediation action |
| `latency_p95_ms` | p95 of `reconstruct_context` wall-clock latency |
| `latency_mean_ms` | mean of `reconstruct_context` wall-clock latency |

## What is judged

Six axes, weighted (indicative):

| Axis | Weight | Source |
|---|---|---|
| `recall@5` | 0.30 | Automated |
| `precision@5_mean` | 0.15 | Automated |
| `remediation_acc` | 0.20 | Automated |
| `latency_p95_ms` vs budget | 0.15 | Automated — scored as `min(1, budget / p95)` |
| `manual_context` | 0.10 | Panel-graded on a sampled subset |
| `manual_explain` | 0.10 | Panel-graded on `explain` field |

Latency budgets: `fast` mode `≤ 2000 ms`, `deep` mode `≤ 6000 ms`.

Weights are illustrative — the technical council may rebalance before the event.

## The central test: topology drift

Families are anchored to a **canonical service id**, but events on the wire carry the **currently-aliased name** at the time of the event. When a service is renamed mid-dataset, the same incident family appears under different service names in train vs eval. A submission that matches by raw string compare on `service` will fail recall on these cases. The engine must recognise behavioural equivalence across the rename boundary.

## Caveats

- Defaults are scaled down so the dummy adapter completes in seconds. Larger scales are exercised at event time via L3 parameters.
- The dummy adapter exists to validate the harness — it matches by exact service-name only and will score poorly on drift cases. Do not benchmark against it.
- Manual axes (`manual_context`, `manual_explain`) are placeholders in the automated runner; the panel scores them post-hoc on sampled outputs.
