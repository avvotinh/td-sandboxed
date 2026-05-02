-- Migration: 005_state_snapshots.sql
-- Adds state_snapshots table for cold storage backup (Story 5.7)
-- Run: psql -d trading -f 005_state_snapshots.sql

-- Check if table exists before creating
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'state_snapshots') THEN
        -- Create table
        CREATE TABLE state_snapshots (
            id UUID DEFAULT gen_random_uuid(),
            account_id VARCHAR(50) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            positions JSONB NOT NULL,
            pending_orders JSONB NOT NULL,
            account_balance DECIMAL(18, 2) NOT NULL,
            equity DECIMAL(18, 2) NOT NULL,
            peak_balance DECIMAL(18, 2) NOT NULL,
            daily_starting_balance DECIMAL(18, 2) NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Convert to hypertable
        PERFORM create_hypertable('state_snapshots', 'timestamp');

        -- Create indexes
        CREATE UNIQUE INDEX idx_state_snapshots_id ON state_snapshots (id, timestamp);
        CREATE INDEX idx_state_snapshots_account ON state_snapshots (account_id, timestamp DESC);

        -- Add foreign key
        ALTER TABLE state_snapshots ADD CONSTRAINT fk_state_snapshots_account
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

        -- Add retention policy
        PERFORM add_retention_policy('state_snapshots', INTERVAL '7 days');

        RAISE NOTICE 'state_snapshots table created successfully';
    ELSE
        RAISE NOTICE 'state_snapshots table already exists, skipping';
    END IF;
END $$;
