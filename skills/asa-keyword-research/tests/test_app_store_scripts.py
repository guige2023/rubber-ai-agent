import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SKILL_DIR / "scripts"
SUGGESTER_SCRIPT = SCRIPT_DIR / "app_store_suggester.py"
SEARCH_SCRIPT = SCRIPT_DIR / "app_store_search.py"


def load_module(module_name: str, path: Path):
    sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_storefront_ids_and_localized_languages_are_configured():
    module = load_module("app_store_suggester", SUGGESTER_SCRIPT)
    suggester = module.AppStoreSuggester()

    assert suggester.countries["US"] == "143441"
    assert suggester.countries["CN"] == "143465"
    assert suggester.countries["JP"] == "143462"
    assert suggester.countries["KR"] == "143466"
    assert suggester.countries["RU"] == "143469"
    assert suggester.countries["SE"] == "143456"
    assert suggester.countries["UA"] == "143492"

    assert suggester.get_language("US") == "en-US,en;q=0.9"
    assert suggester.get_language("CN").startswith("zh-CN")
    assert suggester.get_language("JP").startswith("ja-JP")
    assert suggester.get_language("KR").startswith("ko-KR")
    assert suggester.get_language("JP", "en-US") == "en-US"


def test_app_store_suggester_live_api_returns_suggestions():
    module = load_module("app_store_suggester", SUGGESTER_SCRIPT)
    suggester = module.AppStoreSuggester()

    result = suggester.get_suggestions("scanner", "US")

    assert result["ok"] is True
    assert result["term"] == "scanner"
    assert result["country"] == "US"
    assert result["language"] == "en-US,en;q=0.9"
    assert result["storefront"] == "143441"
    assert isinstance(result["suggestions"], list)
    assert result["suggestions"]
    assert all(isinstance(item, str) and item for item in result["suggestions"])


def test_app_store_search_live_api_returns_candidate_apps():
    module = load_module("app_store_search", SEARCH_SCRIPT)
    client = module.AppStoreSearchClient()

    result = client.search_apps("scanner", "US", limit=5)

    assert result["ok"] is True
    assert result["term"] == "scanner"
    assert result["country"] == "US"
    assert result["language"] == "en-US,en;q=0.9"
    assert result["source"] == "itunes_search_api"
    assert result["result_count"] > 0

    first = result["results"][0]
    assert first["track_id"]
    assert first["track_name"]
    assert first["track_view_url"]


def test_cli_errors_are_structured_json_without_network():
    suggester_result = subprocess.run(
        [sys.executable, str(SUGGESTER_SCRIPT), "--term", "scanner", "--country", "ZZ"],
        capture_output=True,
        text=True,
        check=False,
    )
    search_result = subprocess.run(
        [sys.executable, str(SEARCH_SCRIPT), "--term", "scanner", "--country", "ZZ"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert suggester_result.returncode == 1
    suggester_payload = json.loads(suggester_result.stdout)
    assert suggester_payload["ok"] is False
    assert suggester_payload["error"]["type"] == "SuggestionLookupError"

    assert search_result.returncode == 1
    search_payload = json.loads(search_result.stdout)
    assert search_payload["ok"] is False
    assert search_payload["error"]["type"] == "AppStoreSearchError"
