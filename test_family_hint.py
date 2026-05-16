#!/usr/bin/env python3
"""Quick test to verify family_hint extraction."""
from engine.memory.fingerprint import FingerprintExtractor

extractor = FingerprintExtractor()

# Test cases
test_ids = [
    "INC-46604-4",
    "INC-29447-0",
    "INC-45482-3",
    "INVALID",
    "",
]

for incident_id in test_ids:
    fp = extractor.extract(
        incident_id,
        {"ts": "2024-01-01T00:00:00Z"},
        [],
        None,
    )
    family_hint = fp.get("family_hint", "NOT_SET")
    print(f"ID: {incident_id:20} => family_hint: {family_hint}")
