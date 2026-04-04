CREATE TABLE IF NOT EXISTS traffic_logs (
    id SERIAL PRIMARY KEY,
    junction_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    traffic_volume INT NOT NULL,
    is_peak_hour BOOLEAN NOT NULL,
    is_event BOOLEAN NOT NULL,
    has_incident BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traffic_logs_junction_ts ON traffic_logs (junction_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS decisions (
    id SERIAL PRIMARY KEY,
    junction_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    original_traffic INT NOT NULL,
    z_score FLOAT NOT NULL,
    lanes_allocated INT NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_junction_ts ON decisions (junction_id, timestamp DESC);

CREATE OR REPLACE PROCEDURE cleanup_old_data(days_to_keep INT DEFAULT 7)
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_logs_count INT;
    deleted_decisions_count INT;
BEGIN
    WITH deleted_logs AS (
        DELETE FROM traffic_logs
        WHERE timestamp < NOW() - (days_to_keep || ' days')::INTERVAL
        RETURNING id
    )
    SELECT count(*) INTO deleted_logs_count FROM deleted_logs;

    WITH deleted_decisions AS (
        DELETE FROM decisions
        WHERE timestamp < NOW() - (days_to_keep || ' days')::INTERVAL
        RETURNING id
    )
    SELECT count(*) INTO deleted_decisions_count FROM deleted_decisions;

    RAISE NOTICE 'Deleted % traffic logs and % decisions older than % days.', deleted_logs_count, deleted_decisions_count, days_to_keep;
END;
$$;
