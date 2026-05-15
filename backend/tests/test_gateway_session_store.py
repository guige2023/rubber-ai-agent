"""
Tests for GatewaySessionStore - SQLite session persistence.
"""

import pytest
import tempfile
import os
from datetime import datetime
from pathlib import Path


class TestGatewaySessionStore:
    """Tests for GatewaySessionStore class."""

    def test_init_creates_database(self):
        """Test database initialization."""
        from app.gateway.router import GatewaySessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            store = GatewaySessionStore(db_path)

            assert db_path.exists()

    def test_save_and_load_session(self):
        """Test saving and loading a session."""
        from app.gateway.router import GatewaySessionStore, PlatformIdentity

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            store = GatewaySessionStore(db_path)

            # Create a test session
            identity = PlatformIdentity(
                platform="test",
                user_id="user123",
                chat_id="chat456",
            )
            session = {
                "id": "sess_001",
                "identity": identity,
                "created_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "message_count": 5,
                "platform": "test",
            }

            # Save
            store.save_session("test_key", session)

            # Load
            sessions = store.load_all_sessions()
            assert len(sessions) == 1
            key, loaded = sessions[0]
            assert key == "test_key"
            assert loaded["id"] == "sess_001"

    def test_save_pending_run(self):
        """Test saving pending runs."""
        from app.gateway.router import GatewaySessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            store = GatewaySessionStore(db_path)

            # Save pending run
            store.save_pending_run(
                run_id="run_001",
                session_key="sess_key",
                content="test content",
                metadata={"key": "value"}
            )

            # Retrieve
            runs = store.get_pending_runs("sess_key")
            assert len(runs) == 1
            assert runs[0]["id"] == "run_001"
            assert runs[0]["content"] == "test content"

    def test_resolve_pending_run(self):
        """Test resolving (deleting) pending runs."""
        from app.gateway.router import GatewaySessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            store = GatewaySessionStore(db_path)

            # Save and resolve
            store.save_pending_run("run_001", "sess_key", "content")
            store.resolve_pending_run("run_001")

            # Verify deleted
            runs = store.get_pending_runs("sess_key")
            assert len(runs) == 0

    def test_delete_session(self):
        """Test deleting a session."""
        from app.gateway.router import GatewaySessionStore, PlatformIdentity

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            store = GatewaySessionStore(db_path)

            # Create and save session
            identity = PlatformIdentity(
                platform="test",
                user_id="user123",
                chat_id="chat456",
            )
            session = {
                "id": "sess_001",
                "identity": identity,
                "created_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "message_count": 5,
                "platform": "test",
            }
            store.save_session("test_key", session)

            # Verify exists
            sessions = store.load_all_sessions()
            assert len(sessions) == 1

            # Delete
            store.delete_session("test_key")

            # Verify deleted
            sessions = store.load_all_sessions()
            assert len(sessions) == 0

    def test_get_all_pending_runs(self):
        """Test getting all pending runs across sessions."""
        from app.gateway.router import GatewaySessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            store = GatewaySessionStore(db_path)

            # Save multiple pending runs
            store.save_pending_run("run_001", "sess_1", "content1")
            store.save_pending_run("run_002", "sess_2", "content2")

            # Get all
            runs = store.get_all_pending_runs()
            assert len(runs) == 2


class TestGatewayRouterPersistence:
    """Tests for GatewayRouter persistence integration."""

    @pytest.mark.asyncio
    async def test_router_persists_session_on_create(self):
        """Test that creating a session persists it to SQLite."""
        from app.gateway.router import GatewayRouter, PlatformIdentity

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "router.db"
            router = GatewayRouter(db_path=db_path)

            identity = PlatformIdentity(
                platform="test",
                user_id="user123",
                chat_id="chat456",
            )

            # Route a message (creates session)
            await router.route_incoming(
                platform="test",
                event={"content": "hello"},
                identity=identity,
            )

            # Verify persisted
            sessions = router._session_store.load_all_sessions()
            assert len(sessions) == 1

    @pytest.mark.asyncio
    async def test_router_recover_sessions(self):
        """Test recovering sessions from SQLite on startup."""
        from app.gateway.router import GatewayRouter, PlatformIdentity

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "router.db"

            # Create router and add session
            router1 = GatewayRouter(db_path=db_path)
            identity = PlatformIdentity(
                platform="test",
                user_id="user123",
                chat_id="chat456",
            )
            await router1.route_incoming(
                platform="test",
                event={"content": "hello"},
                identity=identity,
            )

            # Create new router instance (simulates restart)
            router2 = GatewayRouter(db_path=db_path)
            recovered = await router2.recover_sessions()

            assert len(recovered) == 1

    @pytest.mark.asyncio
    async def test_cleanup_stale_sessions_deletes_from_sqlite(self):
        """Test cleanup removes sessions from both memory and SQLite."""
        from app.gateway.router import GatewayRouter, PlatformIdentity

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "router.db"
            router = GatewayRouter(db_path=db_path)

            identity = PlatformIdentity(
                platform="test",
                user_id="user123",
                chat_id="chat456",
            )
            await router.route_incoming(
                platform="test",
                event={"content": "hello"},
                identity=identity,
            )

            # Cleanup with max_age=0 (immediately stale)
            removed = await router.cleanup_stale_sessions(max_age_seconds=0)

            assert removed == 1
            # Verify SQLite also deleted
            sessions = router._session_store.load_all_sessions()
            assert len(sessions) == 0
