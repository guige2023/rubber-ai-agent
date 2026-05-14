import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_submit_targets.py"
SPEC = importlib.util.spec_from_file_location("verify_submit_targets", SCRIPT_PATH)
verify_submit_targets = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verify_submit_targets)


def test_detects_product_submission_paths():
    html = '<a href="/submit-startup">Submit your startup</a>'

    snippet = verify_submit_targets._detect_submit_signal(html)

    assert snippet is not None
    assert "Submit your startup" in snippet
    assert "/submit-startup" in snippet


def test_detects_products_new_paths():
    html = '<a href="https://example.com/products/new">Create a product page</a>'

    snippet = verify_submit_targets._detect_submit_signal(html)

    assert snippet is not None
    assert "Create a product page" in snippet
    assert "/products/new" in snippet


def test_filters_generic_newsletter_submit_button():
    html = """
    <form class="newsletter">
      <input placeholder="Email address" />
      <button type="submit">Submit</button>
    </form>
    """

    snippet = verify_submit_targets._detect_submit_signal(html)

    assert snippet is None


def test_filters_generic_search_submit_button():
    html = """
    <form role="search">
      <input name="q" />
      <button type="submit">Submit</button>
    </form>
    """

    snippet = verify_submit_targets._detect_submit_signal(html)

    assert snippet is None


def test_decodes_html_entities_in_snippet():
    html = '<a href="/get-listed">Get&nbsp;Listed</a>'

    snippet = verify_submit_targets._detect_submit_signal(html)

    assert snippet is not None
    assert "Get Listed" in snippet
