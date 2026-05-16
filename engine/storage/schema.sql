-- Events table — all telemetry events
CREATE TABLE IF NOT EXISTS events (
    id VARCHAR PRIMARY KEY,
    ts TIMESTAMP,
    kind VARCHAR,
    service VARCHAR,
    level VARCHAR,
    msg VARCHAR,
    trace_id VARCHAR,
    name VARCHAR,
    value DOUBLE,
    spans JSON,
    version VARCHAR,
    actor VARCHAR,
    change_type VARCHAR,  -- topology change type
    from_service VARCHAR,
    to_service VARCHAR,
    incident_id VARCHAR,
    trigger VARCHAR,
    action VARCHAR,
    target VARCHAR,
    outcome VARCHAR,
    attrs JSON
);

-- Index on ts for range queries
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

-- Index on kind for filtering
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

-- Index on service for lookups
CREATE INDEX IF NOT EXISTS idx_events_service ON events(service);

-- Index on incident_id for incident lookup
CREATE INDEX IF NOT EXISTS idx_events_incident_id ON events(incident_id);

-- Index on trace_id for trace correlation
CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);

-- Fingerprints table — pre-computed incident signatures
CREATE TABLE IF NOT EXISTS fingerprints (
    incident_id VARCHAR PRIMARY KEY,
    ts TIMESTAMP,
    pattern JSON,  -- behavioral pattern
    vector BLOB,   -- embedding vector
    service VARCHAR,
    severity VARCHAR
);

-- Index on incident_id for lookups
CREATE INDEX IF NOT EXISTS idx_fingerprints_incident_id ON fingerprints(incident_id);
