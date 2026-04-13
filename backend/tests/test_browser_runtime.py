from pathlib import Path

import pytest

from app.core.browser import BrowserController, CHROME_REQUIRED_MESSAGE


def test_browser_launch_plans_do_not_fallback_to_bundled_chromium(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr("app.core.browser.shutil.which", lambda name: None)

    controller = BrowserController()

    assert controller._build_launch_plans() == []


@pytest.mark.asyncio
async def test_browser_enter_shows_install_guidance_when_chrome_missing(monkeypatch):
    async def fake_start():
        return object()

    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr("app.core.browser.shutil.which", lambda name: None)
    monkeypatch.setattr("app.core.browser.async_playwright", lambda: type(
        "FakePlaywrightFactory",
        (),
        {"start": staticmethod(fake_start)},
    )())

    controller = BrowserController()

    with pytest.raises(RuntimeError, match="Chrome runtime is unavailable"):
        await controller.__aenter__()

    assert "https://www.google.com/chrome/" in CHROME_REQUIRED_MESSAGE
