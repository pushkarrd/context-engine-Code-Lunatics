import json
import time
from adapters.myteam import Engine

sample_events = [
    {"ts":"2026-05-10T14:21:30Z","kind":"deploy","service":"payments-svc","version":"v2.14.0","actor":"ci"},
    {"ts":"2026-05-10T14:22:01Z","kind":"log","service":"checkout-api","level":"error","msg":"timeout calling payments-svc","trace_id":"abc123"},
    {"ts":"2026-05-10T14:22:01Z","kind":"metric","service":"payments-svc","name":"latency_p99_ms","value":4820},
    {"ts":"2026-05-10T14:22:08Z","kind":"trace","trace_id":"abc123","spans":[{"svc":"checkout-api","dur_ms":5012},{"svc":"payments-svc","dur_ms":4980}]},
    {"ts":"2026-05-10T14:30:00Z","kind":"topology","change":"rename","from":"payments-svc","to":"billing-svc"},
    {"ts":"2026-05-10T14:32:11Z","kind":"incident_signal","incident_id":"INC-714","trigger":"alert:checkout-api/error-rate>5%"},
    {"ts":"2026-05-10T15:10:00Z","kind":"remediation","incident_id":"INC-714","action":"rollback","target":"billing-svc","version":"v2.13.4","outcome":"resolved"},
]

print("--- STEP 1: Initializing engine ---")
engine = Engine()
print("OK Engine initialized")

print("\n--- STEP 2: Ingesting 7 sample events ---")
engine.ingest(sample_events)
print("OK Events ingested")

print("\n--- STEP 3: Firing incident signal ---")
signal = {
    "incident_id": "INC-714",
    "trigger": "alert:checkout-api/error-rate>5%",
    "ts": "2026-05-10T14:32:11Z",
    "service": "checkout-api"
}

start = time.time()
context = engine.reconstruct_context(signal, mode="fast")
elapsed = time.time() - start
print(f"OK reconstruct_context done in {elapsed:.2f}s")

print("\n--- STEP 4: Checking all required fields ---")
required_fields = ["related_events","causal_chain","similar_past_incidents","suggested_remediations","confidence","explain"]
all_good = True
for field in required_fields:
    if field in context:
        print(f"  OK {field} is present")
    else:
        print(f"  MISSING {field} -- will fail benchmark!")
        all_good = False

print("\n--- STEP 5: Output counts ---")
print(f"  related_events:        {len(context.get('related_events', []))}")
print(f"  causal_chain edges:    {len(context.get('causal_chain', []))}")
print(f"  similar_incidents:     {len(context.get('similar_past_incidents', []))}")
print(f"  remediations:          {len(context.get('suggested_remediations', []))}")
print(f"  confidence:            {context.get('confidence', 0):.2f}")
print(f"  explain preview:       {str(context.get('explain',''))[:120]}")

print("\n--- STEP 6: Latency check ---")
if elapsed < 2.0:
    print(f"  OK Fast mode: {elapsed:.2f}s (limit is 2.0s)")
else:
    print(f"  TOO SLOW: {elapsed:.2f}s (limit is 2.0s) -- fix this!")

engine.close()
print("\n--- DONE ---")