"""
Tests for Curator - skill organization and consolidation.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestCurator:
    """Tests for Curator class."""

    def test_curator_config_defaults(self):
        """Test CuratorConfig default values."""
        from app.core.evolution.curator import CuratorConfig

        config = CuratorConfig()
        assert config.idle_hours == 168  # 7 days
        assert config.min_idle_hours == 1
        assert config.merge_threshold == 3
        assert config.archive_after_days == 30
        assert config.consolidation_interval_hours == 24

    def test_curator_initial_state(self):
        """Test Curator initial state."""
        from app.core.evolution.curator import Curator

        curator = Curator()
        assert curator.config is not None
        assert curator._running is False
        assert curator._task is None
        assert curator._last_run is None
        assert curator._last_activity is None

    @pytest.mark.asyncio
    async def test_curator_start_stop(self):
        """Test Curator start and stop."""
        from app.core.evolution.curator import Curator

        curator = Curator()
        await curator.start()
        assert curator._running is True
        assert curator._task is not None

        await curator.stop()
        assert curator._running is False

    def test_curator_record_activity(self):
        """Test activity recording resets idle timer."""
        from app.core.evolution.curator import Curator

        curator = Curator()
        assert curator._last_activity is None

        curator.record_activity()
        assert curator._last_activity is not None

    def test_curator_get_status(self):
        """Test Curator status reporting."""
        from app.core.evolution.curator import Curator

        curator = Curator()
        status = curator.get_status()

        assert "running" in status
        assert "last_run" in status
        assert "last_activity" in status
        assert "idle_hours" in status
        assert "config" in status


class TestCuratorMergeLogic:
    """Tests for Curator merge logic."""

    @pytest.mark.asyncio
    async def test_analyze_agent_skills_returns_structure(self):
        """Test _analyze_agent_skills returns expected structure."""
        from app.core.evolution.curator import Curator

        curator = Curator()

        # Mock skill_crystal
        with patch.object(curator, 'skill_crystal') as mock_sc:
            mock_sc.client = MagicMock()
            mock_sc.client.execute_query = AsyncMock(return_value=[])

            result = await curator._analyze_agent_skills()

        assert "count" in result
        assert "groups" in result
        assert "skills" in result or "error" in result

    @pytest.mark.asyncio
    async def test_find_merge_candidates_returns_list(self):
        """Test _find_merge_candidates returns list."""
        from app.core.evolution.curator import Curator

        curator = Curator()

        with patch.object(curator, 'skill_crystal') as mock_sc:
            mock_sc.client = MagicMock()
            mock_sc.client.execute_query = AsyncMock(return_value=[])

            result = await curator._find_merge_candidates()
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_archive_stale_skills_returns_count(self):
        """Test _archive_stale_skills returns int."""
        from app.core.evolution.curator import Curator

        curator = Curator()

        with patch.object(curator, 'skill_crystal') as mock_sc:
            mock_sc.client = MagicMock()
            mock_sc.client.execute_query = AsyncMock(return_value=[])

            result = await curator._archive_stale_skills()
            assert isinstance(result, int)


class TestCuratorCuration:
    """Tests for curation process."""

    @pytest.mark.asyncio
    async def test_run_curation_returns_summary(self):
        """Test run_curation returns expected summary structure."""
        from app.core.evolution.curator import Curator

        curator = Curator()
        curator.record_activity()

        # Mock the internal methods
        with patch.object(curator, '_analyze_agent_skills', new_callable=AsyncMock) as mock_analyze, \
             patch.object(curator, '_find_merge_candidates', new_callable=AsyncMock) as mock_find, \
             patch.object(curator, '_create_umbrella_skills', new_callable=AsyncMock) as mock_create, \
             patch.object(curator, '_archive_stale_skills', new_callable=AsyncMock) as mock_archive:

            mock_analyze.return_value = {"count": 0, "groups": []}
            mock_find.return_value = []
            mock_create.return_value = []
            mock_archive.return_value = 0

            result = await curator.run_curation()

        assert "started_at" in result
        assert "skills_analyzed" in result
        assert "skills_merged" in result
        assert "umbrellas_created" in result
        assert "skills_archived" in result
        assert "errors" in result
