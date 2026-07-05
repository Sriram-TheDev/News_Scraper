-- JIT News Vault Database Schema
-- This schema follows the specifications in 03-Database-Schema.md
-- Execute this in your Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- bot_settings table
-- Single-row cardinality table for global tracking configuration
CREATE TABLE bot_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    delivery_time TEXT NOT NULL DEFAULT '08:00',
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    sources TEXT[] DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enforce single-row cardinality
CREATE OR REPLACE FUNCTION enforce_single_row_bot_settings()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM bot_settings WHERE id != NEW.id) THEN
        RAISE EXCEPTION 'bot_settings table must have only one row';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER bot_settings_single_row_trigger
    BEFORE INSERT OR UPDATE ON bot_settings
    FOR EACH ROW
    EXECUTE FUNCTION enforce_single_row_bot_settings();

-- Insert initial row
INSERT INTO bot_settings (id, delivery_time, tags, sources)
VALUES (1, '08:00', ARRAY['tech', 'ai'], ARRAY['https://example.com'])
ON CONFLICT (id) DO NOTHING;

-- url_history table
-- Ledger of previously delivered news elements for deduplication
CREATE TABLE url_history (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create unique index on url for fast deduplication
CREATE INDEX idx_url_history_url ON url_history(url);

-- digest_buffer table
-- Fault-tolerant staging area for undelivered data (Fail-Loud pattern)
CREATE TABLE digest_buffer (
    id SERIAL PRIMARY KEY,
    content_payload TEXT NOT NULL,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'pending'
);

-- Create index on status for state recovery
CREATE INDEX idx_digest_buffer_status ON digest_buffer(status);

-- Enable Row-Level Security on all tables
ALTER TABLE bot_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE url_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE digest_buffer ENABLE ROW LEVEL SECURITY;

-- RLS Policies: Block all public access
-- All access must go through service_role key (backend-only)
CREATE POLICY "No public access to bot_settings" ON bot_settings
    FOR ALL USING (false);

CREATE POLICY "No public access to url_history" ON url_history
    FOR ALL USING (false);

CREATE POLICY "No public access to digest_buffer" ON digest_buffer
    FOR ALL USING (false);

-- Grant service_role full access (this is the backend key)
-- Note: service_role bypasses RLS by default, but we keep policies for documentation
