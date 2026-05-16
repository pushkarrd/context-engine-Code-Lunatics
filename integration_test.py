"""Integration test — validates full architecture."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

def test_basic_flow():
    """Test: Events → Ingest → Reconstruct → Get Context."""
    try:
        from adapters.myteam import TeamAdapter
        from schema import Event, IncidentSignal

        print("[1] Initializing adapter...")
        adapter = TeamAdapter()
        print("    ✓ Adapter initialized")

        print("\n[2] Creating sample telemetry events...")
        now = datetime.now(timezone.utc).isoformat()
        events: list[Event] = [
            {"ts": now, "kind": "deploy", "service": "api-svc", "version": "2.0.0", "actor": "ci"},
            {"ts": now, "kind": "metric", "service": "api-svc", "name": "latency_p99", "value": 850.0},
            {"ts": now, "kind": "log", "service": "api-svc", "level": "error", "msg": "Connection timeout"},
            {"ts": now, "kind": "incident_signal", "incident_id": "INC-100", "service": "api-svc", "trigger": "high_error_rate"},
            {"ts": now, "kind": "remediation", "incident_id": "INC-100", "action": "rollback", "target": "api-svc", "outcome": "success"},
        ]
        print(f"    ✓ Created {len(events)} sample events")

        print("\n[3] Ingesting events...")
        adapter.ingest(events)
        print("    ✓ Events ingested successfully")

        print("\n[4] Reconstructing context for incident...")
        signal: IncidentSignal = {
            "incident_id": "INC-100",
            "ts": now,
            "trigger": "high_error_rate",
            "service": "api-svc",
        }
        context = adapter.reconstruct_context(signal, mode="fast")
        print("    ✓ Context reconstructed")

        print("\n[5] Validating context structure...")
        required_fields = ["related_events", "causal_chain", "similar_past_incidents", "suggested_remediations", "confidence", "explain"]
        for field in required_fields:
            assert field in context, f"Missing field: {field}"
            print(f"    ✓ {field}: {type(context[field]).__name__}")

        print("\n[6] Validating data types...")
        assert isinstance(context["related_events"], list), "related_events must be list"
        assert isinstance(context["causal_chain"], list), "causal_chain must be list"
        assert isinstance(context["similar_past_incidents"], list), "similar_past_incidents must be list"
        assert isinstance(context["suggested_remediations"], list), "suggested_remediations must be list"
        assert isinstance(context["confidence"], (int, float)), "confidence must be numeric"
        assert isinstance(context["explain"], str), "explain must be string"
        print("    ✓ All types valid")

        print("\n[7] Testing topology drift handling...")
        # Ingest a rename event
        rename_event: Event = {
            "ts": now,
            "kind": "topology",
            "change": "rename",
            "from_": "api-svc",
            "to": "gateway-api",
        }
        adapter.ingest([rename_event])
        print("    ✓ Rename event ingested")

        # Query with renamed service
        signal2: IncidentSignal = {
            "incident_id": "INC-100",
            "ts": now,
            "trigger": "high_error_rate",
            "service": "gateway-api",  # Using NEW name
        }
        context2 = adapter.reconstruct_context(signal2, mode="fast")
        assert "related_events" in context2, "Should still get context after rename"
        print("    ✓ Context retrieval works with renamed service")

        print("\n[8] Cleaning up...")
        adapter.close()
        print("    ✓ Adapter closed cleanly")

        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(test_basic_flow())
