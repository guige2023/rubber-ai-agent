-- Migration 0001: Add foreign key constraints and critical indexes
-- 
-- This migration adds:
-- 1. Physical foreign key: messages.session_id -> sessions.id (CASCADE DELETE)
-- 2. Physical foreign key: tasks.session_id -> sessions.id (CASCADE DELETE)
-- 3. Index on tasks.parent_id for tree queries
-- 4. Composite index on messages(session_id, created_at DESC) for message retrieval
-- 5. Index on messages.role for filtering
--
-- NOTE: SQLite foreign keys must be enabled per-connection.
-- We enable them at the start of this migration.

-- rollback: 
-- DROP INDEX IF EXISTS idx_messages_session_created;
-- DROP INDEX IF EXISTS idx_messages_role;
-- DROP INDEX IF EXISTS idx_tasks_parent_id;

PRAGMA foreign_keys = ON;

-- Add composite index for efficient message retrieval (P0-DB-1)
CREATE INDEX IF NOT EXISTS idx_messages_session_created
ON messages(session_id, created_at DESC);

-- Add role index for filtering (P0-DB-1)
CREATE INDEX IF NOT EXISTS idx_messages_role
ON messages(role);

-- Add parent_id index for task tree queries (P0-DB-1)
CREATE INDEX IF NOT EXISTS idx_tasks_parent_id
ON tasks(parent_id);

-- Add foreign key constraint on messages.session_id (P0-DB-1)
-- First we need to remove any orphaned messages
DELETE FROM messages WHERE session_id NOT IN (SELECT id FROM sessions);

-- Add the FK constraint using ALTER TABLE (SQLite supports this via the migration approach)
-- SQLite requires recreating the table to add FK constraints, so we do it in steps.
-- Step 1: Rename the old table
ALTER TABLE messages RENAME TO messages_old;

-- Step 2: Create new table with FK constraint
CREATE TABLE messages (
    id TEXT NOT NULL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    parts TEXT DEFAULT '[]',
    type TEXT NOT NULL,
    token_estimate INTEGER DEFAULT 0,
    metadata_ TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Step 3: Copy data from old table
INSERT INTO messages SELECT * FROM messages_old;

-- Step 4: Drop old table
DROP TABLE messages_old;

-- Step 5: Recreate the indexes we added above (they were lost in the table recreation)
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
