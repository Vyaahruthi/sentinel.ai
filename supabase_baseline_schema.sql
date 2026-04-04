-- Create threshold_history table (if it doesnt exist yet)
CREATE TABLE IF NOT EXISTS threshold_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    computed_at TIMESTAMPTZ DEFAULT NOW(),

    -- The 9 raw metrics
    behaviour_adaptation FLOAT,
    data_bias FLOAT,
    data_drift FLOAT,
    feedback_loop FLOAT,
    silent_drift FLOAT,
    infrastructure_change FLOAT,
    policy_change FLOAT,
    technology_influence FLOAT,
    event_traffic FLOAT,

    -- Z-score evaluation fields
    baseline_mean JSONB DEFAULT NULL,
    baseline_std JSONB DEFAULT NULL,
    z_scores JSONB DEFAULT NULL,
    baseline_locked BOOLEAN DEFAULT FALSE,
    baseline_run_count INTEGER DEFAULT 0
);

-- Note: if threshold_history exists but without new columns, you can add them:
-- ALTER TABLE threshold_history
--   ADD COLUMN IF NOT EXISTS baseline_mean JSONB DEFAULT NULL,
--   ADD COLUMN IF NOT EXISTS baseline_std JSONB DEFAULT NULL,
--   ADD COLUMN IF NOT EXISTS z_scores JSONB DEFAULT NULL,
--   ADD COLUMN IF NOT EXISTS baseline_locked BOOLEAN DEFAULT FALSE,
--   ADD COLUMN IF NOT EXISTS baseline_run_count INTEGER DEFAULT 0;

-- Create sentinel_baseline table
CREATE TABLE IF NOT EXISTS sentinel_baseline (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    run_count INTEGER DEFAULT 0,
    baseline_locked BOOLEAN DEFAULT FALSE,
    baseline_mean JSONB DEFAULT '{}',
    baseline_std JSONB DEFAULT '{}',
    baseline_min_runs INTEGER DEFAULT 30,
    baseline_quality JSONB DEFAULT '{}'
);

-- Insert singleton status row (enforces a solitary record of state)
INSERT INTO sentinel_baseline (id, run_count, baseline_locked) 
VALUES ('00000000-0000-0000-0000-000000000001', 0, false)
ON CONFLICT (id) DO NOTHING;

-- Create traffic_baseline table for lane allocation learning
CREATE TABLE IF NOT EXISTS traffic_baseline (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    congestion_index FLOAT NOT NULL,
    traffic INT,
    capacity INT,
    active_lanes INT,
    threshold_source TEXT
);

-- Add traffic_metrics column to logs table to support boiling frog Phase 1 & 2 logic
ALTER TABLE traffic_logs ADD COLUMN IF NOT EXISTS traffic_metrics JSONB DEFAULT NULL;
