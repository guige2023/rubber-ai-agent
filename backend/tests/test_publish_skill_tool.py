import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.deps import AgentDeps
from app.core.kernel import FerrymanKernel
from app.core.toolkits.skill import SkillToolkit


TEST_ROOT = Path("/tmp/ferryman_publish_skill_test")
TEST_USER_SKILLS = TEST_ROOT / "user" / "skills"
TEST_BUNDLED_SKILLS = TEST_ROOT / "bundled" / "skills"


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)

    TEST_USER_SKILLS.mkdir(parents=True, exist_ok=True)
    TEST_BUNDLED_SKILLS.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FERRYMAN_BUNDLED_SKILLS_DIR", str(TEST_BUNDLED_SKILLS))

    yield

    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


def create_test_settings() -> Settings:
    return Settings(FERRYMAN_ROOT_DIR=TEST_ROOT)


def create_draft_skill(skill_dir: Path, name: str = "draft-skill"):
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Draft skill for publishing
version: 1.0.0
---
# Draft SOP
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_publish_skill_moves_draft_and_registers_it():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "publish-session"
    workspace = kernel.get_session_workspace(session_id)
    draft_dir = workspace / "draft-skill"
    create_draft_skill(draft_dir)

    ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id))

    result = await SkillToolkit.publish_skill(ctx, "draft-skill")
    payload = json.loads(result)

    published_dir = TEST_USER_SKILLS / "draft-skill"
    assert payload["ok"] is True
    assert payload["skill_name"] == "draft-skill"
    assert payload["registered"] is True
    assert published_dir.exists()
    assert not draft_dir.exists()
    assert "draft-skill" in kernel.skills


@pytest.mark.asyncio
async def test_publish_skill_rejects_paths_outside_workspace():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "publish-session"
    outside_dir = TEST_ROOT / "outside-skill"
    create_draft_skill(outside_dir, name="outside-skill")

    ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id))

    with pytest.raises(RuntimeError, match="inside the current session workspace"):
        await SkillToolkit.publish_skill(ctx, str(outside_dir))
