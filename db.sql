-- Create the configuration table for Shannon's Demon
CREATE TABLE IF NOT EXISTS shannon_configs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    asset_a VARCHAR NOT NULL,
    asset_b VARCHAR NOT NULL,
    target_a DOUBLE PRECISION DEFAULT 0.5,
    target_b DOUBLE PRECISION DEFAULT 0.5,
    threshold DOUBLE PRECISION DEFAULT 0.05,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add indexes for faster lookups
CREATE INDEX IF NOT EXISTS ix_shannon_configs_id ON shannon_configs (id);
CREATE INDEX IF NOT EXISTS ix_shannon_configs_user_id ON shannon_configs (user_id);

-- Create the trade history table, linked to the configuration
CREATE TABLE IF NOT EXISTS shannon_trade_history (
    id SERIAL PRIMARY KEY,
    config_id INTEGER NOT NULL REFERENCES shannon_configs(id) ON DELETE CASCADE,
    action VARCHAR NOT NULL,  -- e.g., 'BUY' or 'SELL'
    asset VARCHAR NOT NULL,
    quantity INTEGER NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    reason VARCHAR,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add index for trade history
CREATE INDEX IF NOT EXISTS ix_shannon_trade_history_id ON shannon_trade_history (id);

-- Create table for NSE 100-Bagger scanner results
CREATE TABLE IF NOT EXISTS nse_bagger_scan_results (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR UNIQUE NOT NULL,
    company_name VARCHAR,
    passed BOOLEAN DEFAULT FALSE,
    score DOUBLE PRECISION DEFAULT 0.0,
    pass_ratio DOUBLE PRECISION DEFAULT 0.0,
    label VARCHAR,
    metrics JSONB,
    checks JSONB,
    warnings JSONB,
    missing_fields JSONB,
    explanation TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_nse_bagger_scan_results_ticker ON nse_bagger_scan_results (ticker);
CREATE INDEX IF NOT EXISTS ix_nse_bagger_scan_results_score ON nse_bagger_scan_results (score);

