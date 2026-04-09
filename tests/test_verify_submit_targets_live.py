import importlib.util
import os
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "seo-backlink-research"
    / "scripts"
    / "verify_submit_targets.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_submit_targets_live_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_VERIFY_TESTS") != "1",
    reason="Set RUN_LIVE_VERIFY_TESTS=1 to run live website verification tests.",
)


def test_live_verified_submission_pages():
    module = _load_module()
    cases = [
        ("https://www.toolify.ai/submit", "toolify.ai"),
        ("https://www.futurepedia.io/submit-tool", "futurepedia.io"),
        ("https://www.insidr.ai/", "insidr.ai"),
    ]

    for url, label in cases:
        result = module.verify_url(url, timeout=20)
        assert result.accessible is True, label
        assert result.submit_signal_found is True, label
        assert result.browser_fallback_recommended is False, label
        assert result.verification_method == "http", label


def test_live_http_403_becomes_browser_fallback_candidate():
    module = _load_module()

    result = module.verify_url("https://www.g2.com/categories/artificial-intelligence", timeout=20)

    assert result.accessible is False
    assert result.submit_signal_found is False
    assert result.failure_reason == "HTTP 403"
    assert result.browser_fallback_recommended is True
    assert result.browser_fallback_reason == "HTTP 403"


def test_live_soft_block_page_recommends_visible_browser_follow_up():
    module = _load_module()

    result = module.verify_url("https://www.producthunt.com/", timeout=20)

    assert result.accessible is True
    assert result.submit_signal_found is False
    assert result.browser_fallback_recommended is True
    assert result.browser_fallback_reason == "anti_bot_or_human_verification_page"
