import importlib.util
from pathlib import Path
from urllib.error import HTTPError

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "seo-backlink-research"
    / "scripts"
    / "verify_submit_targets.py"
)


@pytest.fixture(scope="module")
def verify_submit_targets_module():
    spec = importlib.util.spec_from_file_location("verify_submit_targets_test_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, html: str, final_url: str = "https://example.com/page"):
        self._html = html
        self._final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size: int = -1):
        return self._html.encode("utf-8")

    def geturl(self):
        return self._final_url


def test_verify_url_recommends_browser_for_js_rendered_pages(monkeypatch, verify_submit_targets_module):
    html = """
    <html>
      <head>
        <script src="/static/runtime.js"></script>
        <script>window.__NUXT__ = {};</script>
      </head>
      <body>
        <div id="__nuxt"></div>
      </body>
    </html>
    """

    monkeypatch.setattr(
        verify_submit_targets_module,
        "urlopen",
        lambda request, timeout=10.0: FakeResponse(html, "https://example.com/directory"),
    )

    result = verify_submit_targets_module.verify_url("https://example.com/directory")

    assert result.accessible is True
    assert result.submit_signal_found is False
    assert result.verification_method == "http"
    assert result.browser_fallback_recommended is True
    assert result.browser_fallback_reason == "client_side_rendering_suspected"


def test_verify_url_recommends_browser_for_human_verification_pages(monkeypatch, verify_submit_targets_module):
    html = """
    <html>
      <body>
        <h1>Checking your browser before accessing the site</h1>
        <p>Cloudflare</p>
      </body>
    </html>
    """

    monkeypatch.setattr(
        verify_submit_targets_module,
        "urlopen",
        lambda request, timeout=10.0: FakeResponse(html, "https://example.com/challenge"),
    )

    result = verify_submit_targets_module.verify_url("https://example.com/challenge")

    assert result.accessible is True
    assert result.submit_signal_found is False
    assert result.browser_fallback_recommended is True
    assert result.browser_fallback_reason == "anti_bot_or_human_verification_page"


def test_verify_url_keeps_positive_submit_signal_without_browser_fallback(monkeypatch, verify_submit_targets_module):
    html = """
    <html>
      <body>
        <a href="/submit-your-tool">Submit your tool</a>
      </body>
    </html>
    """

    monkeypatch.setattr(
        verify_submit_targets_module,
        "urlopen",
        lambda request, timeout=10.0: FakeResponse(html, "https://example.com/submit"),
    )

    result = verify_submit_targets_module.verify_url("https://example.com/submit")

    assert result.accessible is True
    assert result.submit_signal_found is True
    assert "Submit your tool" in (result.submit_signal_snippet or "")
    assert result.browser_fallback_recommended is False
    assert result.browser_fallback_reason is None


def test_verify_url_marks_http_403_as_browser_fallback_candidate(monkeypatch, verify_submit_targets_module):
    def raise_http_error(request, timeout=10.0):
        raise HTTPError(
            url="https://example.com/protected",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(verify_submit_targets_module, "urlopen", raise_http_error)

    result = verify_submit_targets_module.verify_url("https://example.com/protected")

    assert result.accessible is False
    assert result.submit_signal_found is False
    assert result.failure_reason == "HTTP 403"
    assert result.browser_fallback_recommended is True
    assert result.browser_fallback_reason == "HTTP 403"
