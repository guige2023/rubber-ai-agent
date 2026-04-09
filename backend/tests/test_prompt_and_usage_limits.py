import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.usage import RunUsage

from app.core.config import Settings
from app.core.deps import AgentDeps
from app.core.kernel import FerrymanKernel
from app.core.toolkits.skill import SkillToolkit
from app.models.schemas import Usage


TEST_ROOT = Path("/tmp/ferryman_prompt_usage_test")
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


def create_mock_skill(name: str, desc: str, directory: Path):
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    content = f"""---
name: {name}
description: {desc}
version: 1.0.0
---
# Mock SOP
"""
    skill_md.write_text(content, encoding="utf-8")


def test_runtime_context_moves_to_user_prompt():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "test-session"

    system_prompt = kernel._build_system_prompt(session_id)
    augmented_instruction = kernel.build_runtime_augmented_instruction("Inspect files", session_id)

    assert "Host OS:" not in system_prompt
    assert "Root Dir:" not in system_prompt
    assert "Session Workspace:" not in system_prompt

    assert "Host OS:" in augmented_instruction
    assert "Root Dir:" in augmented_instruction
    assert "Session Workspace:" in augmented_instruction
    assert "Current Date:" in augmented_instruction
    assert "Time Zone:" in augmented_instruction
    assert "Inspect files" in augmented_instruction


@pytest.mark.asyncio
async def test_skill_run_uses_shared_usage_and_request_limit(monkeypatch):
    create_mock_skill("target_skill", "Test skill", TEST_USER_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()

    def settings_get(key: str, default=None):
        if key == "system.llm.request_limit":
            return 42
        return Settings.get(key, default)

    monkeypatch.setattr(type(kernel._settings), "get", staticmethod(settings_get))

    captured = {}

    class MockSkillResult:
        output = "skill-ok"

        @staticmethod
        def usage():
            return Usage(input_tokens=1, output_tokens=2, total_tokens=3)

    class MockSkillAgent:
        async def run(self, instruction, **kwargs):
            captured["instruction"] = instruction
            captured["kwargs"] = kwargs
            return MockSkillResult()

    monkeypatch.setattr(kernel, "build_skill_agent", lambda skill_name: MockSkillAgent())

    shared_usage = RunUsage()
    ctx = SimpleNamespace(
        deps=AgentDeps(kernel=kernel, session_id="test-session"),
        usage=shared_usage,
    )

    result = await SkillToolkit.run_skill(ctx, "target_skill", "Do the skill work")

    assert result == "skill-ok"
    assert captured["kwargs"]["usage"] is shared_usage
    assert captured["kwargs"]["usage_limits"].request_limit == 42
    assert "Session Workspace:" in captured["instruction"]
    assert "Do the skill work" in captured["instruction"]
