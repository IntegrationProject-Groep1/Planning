-- Migration 010: Add price column to sessions
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS price NUMERIC(10,2);
