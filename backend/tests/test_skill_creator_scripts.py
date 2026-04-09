import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SCRIPT = REPO_ROOT / "skills" / "skill-creator" / "scripts" / "init_skill.py"
VALIDATE_SCRIPT = REPO_ROOT / "skills" / "skill-creator" / "scripts" / "quick_validate.py"


def test_init_skill_creates_draft_structure(tmp_path):
    output_dir = tmp_path / "workspace"
    result = subprocess.run(
        [
            sys.executable,
            str(INIT_SCRIPT),
            "demo-skill",
            "--description",
            "Demo trigger description",
            "--output-dir",
            str(output_dir),
            "--with-scripts",
            "--with-references",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    draft_dir = output_dir / "demo-skill"
    assert result.stdout.strip() == str(draft_dir)
    assert (draft_dir / "SKILL.md").exists()
    assert (draft_dir / "scripts").is_dir()
    assert (draft_dir / "references").is_dir()


def test_quick_validate_accepts_valid_skill(tmp_path):
    draft_dir = tmp_path / "demo-skill"
    draft_dir.mkdir()
    (draft_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo trigger description
---
# Demo Skill
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(draft_dir)],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["metadata"]["name"] == "demo-skill"


def test_quick_validate_rejects_name_mismatch(tmp_path):
    draft_dir = tmp_path / "wrong-folder"
    draft_dir.mkdir()
    (draft_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo trigger description
---
# Demo Skill
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(draft_dir)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert any("Directory name" in item for item in payload["errors"])
