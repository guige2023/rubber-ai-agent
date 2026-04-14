from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent


def required_paths(app_path: Path) -> list[Path]:
    resources = app_path / "Contents" / "Resources" / "gen"
    return [
        resources / "backend-sidecar" / "ferryman",
        resources / "backend-sidecar" / "_internal" / "playwright_stealth" / "js" / "generate.magic.arrays.js",
        resources / "backend-sidecar" / "_internal" / "trafilatura" / "settings.cfg",
        resources / "backend-sidecar" / "_internal" / "justext" / "stoplists",
        resources / "skills",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the packaged Ferryman macOS bundle.")
    parser.add_argument(
        "--app-path",
        default=str(ROOT / "src-tauri" / "target" / "release" / "bundle" / "macos" / "Ferryman.app"),
        help="Path to the built Ferryman.app bundle.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app_path = Path(args.app_path).resolve()
    if not app_path.exists():
        raise RuntimeError(f"App bundle not found at {app_path}")

    missing = [str(path) for path in required_paths(app_path) if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing required packaged resources: {missing}")

    stoplists_dir = app_path / "Contents" / "Resources" / "gen" / "backend-sidecar" / "_internal" / "justext" / "stoplists"
    if not any(stoplists_dir.glob("*.txt")):
        raise RuntimeError(f"Packaged jusText stoplists directory is empty: {stoplists_dir}")

    sidecar = app_path / "Contents" / "Resources" / "gen" / "backend-sidecar" / "ferryman"
    skills_dir = app_path / "Contents" / "Resources" / "gen" / "skills"

    with tempfile.TemporaryDirectory(prefix="ferryman-release-smoke-") as temp_root:
        env = os.environ.copy()
        env["FERRYMAN_ROOT_DIR"] = temp_root
        env["FERRYMAN_BUNDLED_SKILLS_DIR"] = str(skills_dir)
        env["PYDANTIC_DISABLE_PLUGINS"] = "1"
        result = subprocess.run(
            [str(sidecar), "--smoke-test-bundle"],
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    if result.returncode != 0:
        raise RuntimeError(
            "Bundled sidecar smoke test failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError(f"Could not parse bundled smoke test output: {result.stdout}") from exc

    dist_dir = PROJECT_ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    shutil.copytree(app_path, dist_dir / app_path.name, dirs_exist_ok=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
