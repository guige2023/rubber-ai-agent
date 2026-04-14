from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace

from pydantic_ai.usage import RequestUsage, Usage

from app.core.browser import BrowserController
from app.core.config import get_settings
from app.core.deps import AgentDeps
from app.core.kernel import FerrymanKernel
from app.core.toolkits.command import CommandToolkit
from app.core.toolkits.file import FileToolkit
from app.core.toolkits.skill import SkillToolkit
from app.core.toolkits.task import TaskToolkit
from app.core.toolkits.web import WebToolkit


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _write_smoke_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            "description: Bundle smoke test skill\n"
            "version: 1.0.0\n"
            "author: Ferryman\n"
            "created: 2026-04-14\n"
            "updated: 2026-04-14\n"
            "---\n\n"
            "# Bundle Smoke Skill\n"
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "echo.py").write_text(
        "import json\nprint(json.dumps({'ok': True, 'source': 'bundle-smoke-script'}))\n",
        encoding="utf-8",
    )


def _write_smoke_page(target: Path) -> None:
    target.write_text(
        """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Ferryman Bundle Smoke</title>
  </head>
  <body>
    <main>
      <h1>Bundle smoke article</h1>
      <p>
        Ferryman bundle smoke validation checks that packaged browser tools can navigate,
        inspect page structure, distill readable content, and interact with form controls
        after the desktop release build is assembled.
      </p>
      <label for="name">Name</label>
      <input id="name" type="text" placeholder="Your name" />
      <button id="confirm" onclick="document.getElementById('status').innerText = 'Confirmed: ' + document.getElementById('name').value;">
        Confirm
      </button>
      <div id="status">Pending</div>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )


async def run_bundle_smoke_test() -> dict[str, object]:
    settings = get_settings()
    kernel = FerrymanKernel(settings)
    session_id = "bundle-smoke"
    workspace = kernel.get_session_workspace(session_id)
    base_ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id), usage=Usage())
    report: dict[str, object] = {"root_dir": str(settings.root_dir), "checks": []}

    try:
        kernel.scan_skills()
        report["checks"].append({"name": "scan_skills", "count": len(kernel.skills)})
        _require(bool(kernel.skills), "No skills were loaded from the bundled skill directories.")

        write_result = await FileToolkit.write_file(base_ctx, "notes/hello.txt", "bundle smoke")
        _require("Successfully wrote" in write_result, f"Unexpected write_file result: {write_result}")
        read_result = await FileToolkit.read_file(base_ctx, "notes/hello.txt")
        _require(read_result == "bundle smoke", f"Unexpected read_file result: {read_result!r}")
        list_result = await FileToolkit.list_files(base_ctx, "notes")
        _require("hello.txt" in list_result, f"list_files did not include hello.txt: {list_result}")
        report["checks"].append({"name": "file_tools"})

        task_result = await TaskToolkit.create_task(
            base_ctx,
            title="Bundle smoke task",
            instruction="Verify packaged task persistence.",
            metadata={"scope": "bundle-smoke"},
        )
        task_id_match = re.search(r"ID=([^,]+)", task_result)
        _require(task_id_match is not None, f"Could not parse task id from: {task_result}")
        task_id = task_id_match.group(1)
        update_result = await TaskToolkit.update_task(base_ctx, task_id, "running", "bundle smoke running")
        _require(task_id in update_result, f"Unexpected update_task result: {update_result}")
        task_listing = await TaskToolkit.list_tasks(base_ctx, query="bundle-smoke")
        _require("Bundle smoke task" in task_listing, f"list_tasks missing bundle smoke task: {task_listing}")
        schedule_result = await TaskToolkit.create_schedule(
            base_ctx,
            name="bundle-smoke-schedule",
            cron_expression="0 * * * *",
            instruction="Verify packaged schedule persistence.",
        )
        _require("bundle-smoke-schedule" in schedule_result, f"Unexpected create_schedule result: {schedule_result}")
        schedule_listing = await TaskToolkit.list_schedules(base_ctx)
        _require("bundle-smoke-schedule" in schedule_listing, f"list_schedules missing schedule: {schedule_listing}")
        report["checks"].append({"name": "task_tools"})

        draft_skill_dir = workspace / "bundle-smoke-skill"
        _write_smoke_skill(draft_skill_dir, "bundle-smoke-skill")
        publish_result = json.loads(await SkillToolkit.publish_skill(base_ctx, "bundle-smoke-skill"))
        _require(publish_result["ok"] is True, f"publish_skill failed: {publish_result}")
        _require("bundle-smoke-skill" in kernel.skills, "Published smoke skill was not registered.")

        skill_ctx = SimpleNamespace(
            deps=AgentDeps(kernel=kernel, session_id=session_id, skill_name="bundle-smoke-skill"),
            usage=Usage(),
        )
        skill_files = await FileToolkit.list_files(skill_ctx, str(kernel.skills["bundle-smoke-skill"].path))
        _require("SKILL.md" in skill_files, f"Published skill resources not readable: {skill_files}")
        command_result = json.loads(await CommandToolkit.run_skill_script(skill_ctx, "echo.py"))
        _require(command_result["ok"] is True, f"run_skill_script failed: {command_result}")
        _require("bundle-smoke-script" in command_result["stdout"], f"Unexpected script stdout: {command_result}")

        original_build_skill_agent = kernel.build_skill_agent

        class FakeSkillResult:
            output = "bundle-smoke-skill-ran"

            @staticmethod
            def usage():
                return RequestUsage(input_tokens=1, output_tokens=1)

        class FakeSkillAgent:
            async def run(self, instruction, deps, usage, usage_limits):
                _require("Runtime Context:" in instruction, "Skill instruction was not runtime-augmented.")
                _require(deps.skill_name == "bundle-smoke-skill", "Skill deps did not carry the active skill name.")
                _require(usage is skill_ctx.usage, "Skill usage object was not forwarded.")
                return FakeSkillResult()

        kernel.build_skill_agent = MethodType(lambda self, skill_name: FakeSkillAgent(), kernel)
        try:
            skill_run_result = await SkillToolkit.run_skill(skill_ctx, "bundle-smoke-skill", "Run smoke skill")
        finally:
            kernel.build_skill_agent = original_build_skill_agent
        _require(skill_run_result == "bundle-smoke-skill-ran", f"run_skill returned unexpected output: {skill_run_result}")
        report["checks"].append({"name": "skill_tools"})

        browser_status = BrowserController.get_runtime_status()
        _require(browser_status["available"] is True, f"System Chrome unavailable for bundle smoke test: {browser_status}")

        smoke_page = workspace / "bundle-smoke.html"
        _write_smoke_page(smoke_page)
        navigate_result = await WebToolkit.browser_navigate(base_ctx, smoke_page.as_uri())
        _require("Successfully navigated" in navigate_result, f"browser_navigate failed: {navigate_result}")
        snapshot = await WebToolkit.browser_aria_snapshot(base_ctx)
        textbox_match = re.search(r'textbox.*\[(\d+)\]', snapshot)
        button_match = re.search(r'button.*\[(\d+)\]', snapshot)
        _require(textbox_match is not None, f"ARIA snapshot missing textbox id: {snapshot}")
        _require(button_match is not None, f"ARIA snapshot missing button id: {snapshot}")

        type_result = await WebToolkit.browser_type(base_ctx, textbox_match.group(1), "Ferryman")
        _require("Successfully typed" in type_result, f"browser_type failed: {type_result}")
        click_result = await WebToolkit.browser_click(base_ctx, button_match.group(1))
        _require("Successfully clicked" in click_result, f"browser_click failed: {click_result}")
        wait_result = await WebToolkit.browser_wait(base_ctx, 200)
        _require("Waited for 200ms." == wait_result, f"Unexpected browser_wait result: {wait_result}")
        distilled = await WebToolkit.browser_get_distilled_dom(base_ctx)
        _require("Bundle smoke article" in distilled, f"browser_get_distilled_dom failed: {distilled[:200]}")

        browser = await kernel.get_browser(session_id)
        page_status = await browser._page.evaluate("document.getElementById('status').innerText")
        _require(page_status == "Confirmed: Ferryman", f"Browser interaction did not update page state: {page_status}")
        screenshot = await WebToolkit.browser_screenshot(base_ctx)
        _require(bool(getattr(screenshot, "data", b"")), "browser_screenshot returned empty image data.")
        report["checks"].append({"name": "web_tools"})

        return report
    finally:
        await kernel.shutdown()


def main() -> int:
    report = asyncio.run(run_bundle_smoke_test())
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
