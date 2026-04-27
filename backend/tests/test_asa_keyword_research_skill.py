import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "asa-keyword-research" / "scripts" / "app_store_suggester.py"


def load_suggester_module():
    spec = importlib.util.spec_from_file_location("app_store_suggester", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asa_suggester_uses_verified_storefront_ids():
    module = load_suggester_module()
    suggester = module.AppStoreSuggester()

    assert suggester.countries["RU"] == "143469"
    assert suggester.countries["SE"] == "143456"
    assert suggester.countries["UA"] == "143492"
    assert suggester.countries["KR"] == "143466"


def test_asa_suggester_cli_returns_nonzero_json_error_for_bad_country():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--term", "scanner", "--country", "ZZ"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "SuggestionLookupError"
    assert "未知国家代码" in payload["error"]["message"]
