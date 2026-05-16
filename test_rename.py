import time
from adapters.myteam import Engine

engine = Engine()

# PAST incident — service called payments-svc
past_events = [
    {"ts":"2026-01-01T10:00:00Z","kind":"deploy","service":"payments-svc","version":"v1.5.0","actor":"ci"},
    {"ts":"2026-01-01T10:02:00Z","kind":"metric","service":"payments-svc","name":"latency_p99_ms","value":3500},
    {"ts":"2026-01-01T10:03:00Z","kind":"log","service":"checkout-api","level":"error","msg":"timeout calling payments-svc","trace_id":"xyz999"},
    {"ts":"2026-01-01T10:05:00Z","kind":"incident_signal","incident_id":"INC-201","trigger":"alert:checkout-api/error-rate>5%"},
    {"ts":"2026-01-01T10:30:00Z","kind":"remediation","incident_id":"INC-201","action":"rollback","target":"payments-svc","version":"v1.4.9","outcome":"resolved"},
]

# Rename event
rename_event = {"ts":"2026-03-01T00:00:00Z","kind":"topology","change":"rename","from":"payments-svc","to":"billing-svc"}

# NEW incident — same service now called billing-svc
new_events = [
    {"ts":"2026-05-10T14:21:30Z","kind":"deploy","service":"billing-svc","version":"v2.14.0","actor":"ci"},
    {"ts":"2026-05-10T14:22:01Z","kind":"metric","service":"billing-svc","name":"latency_p99_ms","value":4820},
    {"ts":"2026-05-10T14:22:01Z","kind":"log","service":"checkout-api","level":"error","msg":"timeout calling billing-svc","trace_id":"abc123"},
    {"ts":"2026-05-10T14:32:11Z","kind":"incident_signal","incident_id":"INC-714","trigger":"alert:checkout-api/error-rate>5%"},
]

print("Ingesting past incident with payments-svc...")
engine.ingest(past_events)
print("OK")

print("Ingesting rename: payments-svc -> billing-svc...")
engine.ingest([rename_event])
print("OK")

print("Ingesting new incident with billing-svc...")
engine.ingest(new_events)
print("OK")

print("\nCalling reconstruct_context for INC-714...")
signal = {
    "incident_id": "INC-714",
    "trigger": "alert:checkout-api/error-rate>5%",
    "ts": "2026-05-10T14:32:11Z",
    "service": "checkout-api"
}

context = engine.reconstruct_context(signal, mode="fast")

print("\n========== RENAME ROBUSTNESS RESULT ==========")
similar = context.get("similar_past_incidents", [])
print(f"Similar incidents found: {len(similar)}")

found = any("INC-201" in str(s) for s in similar)

if found:
    print("PASSED -- INC-201 found despite rename!")
    for s in similar:
        print(f"  Match: {s}")
else:
    print("FAILED -- INC-201 not found after rename")
    print("  Fix: check alias_registry.py and fingerprint.py")

remediations = context.get("suggested_remediations", [])
print(f"\nRemediations suggested: {len(remediations)}")
for r in remediations:
    print(f"  {r}")

print(f"\nExplain: {context.get('explain','')[:200]}")
engine.close()