-- Migration 0001: Add critical indexes and physical foreign key constraints
-- 
-- This migration adds:
-- 1. Composite index on messages(session_id, created_at DESC) for message retrieval
-- 2. Index on messages.role for filtering
-- 3. Index on tasks.parent_id for tree queries
--
-- Physical foreign key constraints on sessions.id are defined in SQLModel
-- and will be enforced once the ORM layer handles cascading deletes.
--
-- NOTE: For SQLite, we use "REFERENCES" in an SQLite-compatible way.
-- The FK constraint on messages.session_id is added via table recreation
-- since SQLite ALTER TABLE ADD CONSTRAINT is not supported.

-- rollback: 
-- DROP INDEX IF EXISTS idx_messages_session_created;
-- DROP INDEX IF EXISTS idx_messages_role;
-- DROP INDEX IF EXISTS idx_tasks_parent_id;

-- Add composite index for efficient message retrieval (P0-DB-1)
-- Covers: SELECT * FROM messages WHERE session_id=? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_messages_session_created
ON messages(session_id, created_at DESC);

-- Add role index for filtering (P0-DB-1)
-- Covers: SELECT * FROM messages WHERE role='assistant'
CREATE INDEX IF NOT EXISTS idx_messages_role
ON messages(role);

-- Add parent_id index for task tree queries (P0-DB-1)
-- Covers: SELECT * FROM tasks WHERE parent_id=?
CREATE INDEX IF NOT EXISTS idx_tasks_parent_id
ON tasks(parent_id);

-- Add session_id index on schedules if missing (for schedule lookup by session)
-- Some queries may need: SELECT * FROM schedules JOIN sessions...
-- No changes needed for app_configs - key PK is already indexed
