from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.toolkits.time import TimeToolkit


def make_ctx():
    return SimpleNamespace(deps=SimpleNamespace())


@pytest.mark.asyncio
async def test_get_current_time_returns_parseable_local_iso_8601_string():
    payload = await TimeToolkit.get_current_time(make_ctx())

    local_time = datetime.fromisoformat(payload)

    assert local_time.tzinfo is not None
