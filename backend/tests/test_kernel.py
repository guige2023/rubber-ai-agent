import pytest
import shutil
from pathlib import Path

from app.core.config import Settings
from app.core.kernel import FerrymanKernel
from app.models.schemas import TaskStatus

# Define test paths
TEST_ROOT = Path("/tmp/ferryman_test")
TEST_USER_SKILLS = TEST_ROOT / "user" / "skills"
TEST_BUNDLED_SKILLS = TEST_ROOT / "bundled" / "skills"
TEST_WORKSPACES = TEST_ROOT / "workspaces"

@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    # Clean up before test
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)

    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    TEST_USER_SKILLS.mkdir(parents=True, exist_ok=True)
    TEST_BUNDLED_SKILLS.mkdir(parents=True, exist_ok=True)
    TEST_WORKSPACES.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("FERRYMAN_BUNDLED_SKILLS_DIR", str(TEST_BUNDLED_SKILLS))

    yield

    # Clean up after test
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


def create_test_settings() -> Settings:
    return Settings(FERRYMAN_ROOT_DIR=TEST_ROOT)

def create_mock_skill(name: str, desc: str, directory: Path):
    """Utility to create a mock skill directory."""
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

def test_ferryman_kernel_tasks(session):
    kernel = FerrymanKernel(create_test_settings())
    
    # Test task creation
    task = kernel.create_task("session-123", "Test Task")
    assert task.title == "Test Task"
    assert task.session_id == "session-123"
    assert task.status == TaskStatus.PENDING
    
    # Test task update
    kernel.update_task(task.id, status=TaskStatus.RUNNING, metadata={"foo": "bar"})
    
def test_scan_skills_and_xml_index():
    create_mock_skill("user_skill", "User skill desc", TEST_USER_SKILLS)
    create_mock_skill("internal_skill", "Internal skill desc", TEST_BUNDLED_SKILLS)

    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    assert "user_skill" in kernel.skills
    assert "internal_skill" in kernel.skills
    
    # Test XML generation (OS Prompt formatting)
    xml = kernel.get_skill_index_xml()
    assert "<available_skills>" in xml
    assert "<name>user_skill</name>" in xml
    assert "<description>Internal skill desc</description>" in xml

def test_read_skill_sop():
    create_mock_skill("target_skill", "Test", TEST_USER_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    
    sop = kernel.read_skill_sop("target_skill")
    assert "Mock SOP" in sop
    
    error_sop = kernel.read_skill_sop("non_existent")
    assert "Error: Skill 'non_existent' not found" in error_sop

@pytest.mark.asyncio
async def test_run_master_agent_mocked(monkeypatch):
    """
    Test Master Agent execution flow.
    """
    class MockResult:
        def __init__(self, data):
            self.data = data
            self.output = data

    class MockAgent:
        async def run(self, instruction, deps=None, message_history=None):
            return MockResult("Master Agent executed: " + instruction)

    def mock_get_master_agent(session_id: str):
        return MockAgent()

    kernel = FerrymanKernel(create_test_settings())
    # Mock the internal agent factory
    monkeypatch.setattr(kernel, "_get_master_agent", mock_get_master_agent)
    
    response = await kernel.run_master_agent("Please list files", "test-session")
    
    assert "Please list files" in response["response"]
