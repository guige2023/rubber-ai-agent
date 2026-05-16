"""
Browser-use based automation - high-level browser workflows.

Wraps browser-use (Playwright) to provide:
- Form filling automation
- Login flow automation
- Multi-step action sequences

Uses the isolated venv: ~/.venv/browser-use/bin/python
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Path to the browser-use venv Python
BROWSER_USE_PYTHON = os.path.expanduser("~/.venv/browser-use/bin/python")

# Fallback system Python if venv not available
SYSTEM_PYTHON = "/opt/homebrew/bin/python3.13"


def _resolve_python() -> str:
    if Path(BROWSER_USE_PYTHON).exists():
        return BROWSER_USE_PYTHON
    return SYSTEM_PYTHON


# ------------------------------------------------------------------
# Data Models
# ------------------------------------------------------------------


class StepType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    PRESS = "press"
    WAIT = "wait"
    WAIT_SELECTOR = "wait_selector"
    SCREENSHOT = "screenshot"
    SNAPSHOT = "snapshot"
    WAIT_NAVIGATION = "wait_navigation"
    SELECT_DROPDOWN = "select_dropdown"
    CHECK = "check"
    HOVER = "hover"


@dataclass
class FormField:
    """A single form field definition."""

    selector: str
    value: str
    field_type: str = "text"  # text, password, email, checkbox, select, radio

    def to_dict(self) -> dict:
        return {
            "selector": self.selector,
            "value": self.value,
            "field_type": self.field_type,
        }


@dataclass
class AutomationStep:
    """A single step in an automation workflow."""

    step_type: StepType
    # For click/type/hover/select
    selector: Optional[str] = None
    text: Optional[str] = None
    # For navigate
    url: Optional[str] = None
    # For wait
    timeout_ms: int = 5000
    # For select_dropdown
    option_value: Optional[str] = None
    option_label: Optional[str] = None
    # For press
    keys: Optional[str] = None
    # Checkbox state
    checked: Optional[bool] = None
    # Navigation wait
    wait_for_url: Optional[str] = None


@dataclass
class LoginFlow:
    """Pre-defined login flow configuration."""

    name: str
    url: str
    username_field: str
    password_field: str
    username: str
    password: str
    submit_button: str
    # Optional: extra steps after login (e.g., 2FA, consent dialogs)
    extra_steps: list[AutomationStep] = field(default_factory=list)
    # Success indicators
    success_indicators: list[str] = field(default_factory=list)
    # Failure indicators
    failure_indicators: list[str] = field(default_factory=list)


@dataclass
class AutomationResult:
    """Result of an automation run."""

    success: bool
    steps_completed: int
    total_steps: int
    screenshot: Optional[str] = None  # base64 encoded
    error: Optional[str] = None
    final_url: Optional[str] = None
    final_title: Optional[str] = None
    captured_text: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "screenshot": self.screenshot,
            "error": self.error,
            "final_url": self.final_url,
            "final_title": self.final_title,
            "captured_text": self.captured_text,
            "details": self.details,
        }


# ------------------------------------------------------------------
# Script Generation (writes data to temp file to avoid quoting issues)
# ------------------------------------------------------------------


_FORM_FILL_TEMPLATE = """
import sys
import json
import time as _time
from pathlib import Path
from browser_use import Controller
from playwright.sync_api import sync_playwright

data_path = sys.argv[1] if len(sys.argv) > 1 else None
if data_path:
    with open(data_path) as f:
        data = json.load(f)
else:
    data = {}

url = data.get("url", "")
fields = data.get("fields", [])
submit_selector = data.get("submit_selector", "")
wait_for_selectors = data.get("wait_for_selectors", [])
screenshot_on_error = data.get("screenshot_on_error", True)

controller = Controller()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    result = {"success": False, "error": None, "url": None, "title": None, "screenshot": None}

    try:
        # Navigate
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # Fill fields
        for field_def in fields:
            selector = field_def["selector"]
            value = field_def["value"]
            field_type = field_def.get("field_type", "text")

            if field_type == "checkbox":
                is_checked = page.is_checked(selector, timeout=3000) if page.query_selector(selector) else False
                target_checked = field_def.get("checked", True)
                if is_checked != target_checked:
                    page.check(selector, timeout=3000) if target_checked else page.uncheck(selector, timeout=3000)
            elif field_type == "select":
                val = field_def.get("option_value") or field_def.get("option_label", "")
                if val:
                    page.select_option(selector, value=val, timeout=3000)
            else:
                page.fill(selector, value, timeout=5000)

        # Click submit
        page.click(submit_selector, timeout=5000)

        # Wait for result selectors
        for sel in wait_for_selectors:
            try:
                page.wait_for_selector(sel, timeout=10000)
            except Exception:
                pass

        result["success"] = True
        result["url"] = page.url
        result["title"] = page.title()

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["url"] = page.url
        result["title"] = page.title()
        if screenshot_on_error:
            try:
                ss = page.screenshot(full_page=False)
                result["screenshot"] = __import__("base64").b64encode(ss).decode()
            except Exception:
                pass

    print(json.dumps(result))
    browser.close()
"""


_LOGIN_TEMPLATE = """
import sys
import json
import time as _time
from browser_use import Controller
from playwright.sync_api import sync_playwright

data_path = sys.argv[1] if len(sys.argv) > 1 else None
if data_path:
    with open(data_path) as f:
        flow = json.load(f)
else:
    flow = {}

controller = Controller()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    result = {"success": False, "error": None, "url": None, "title": None, "screenshot": None}

    try:
        # Navigate to login page
        page.goto(flow["url"], wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # Fill username
        page.fill(flow["username_field"], flow["username"], timeout=5000)

        # Fill password
        page.fill(flow["password_field"], flow["password"], timeout=5000)

        # Extra pre-submit steps (e.g., accept terms, select org)
        for step in flow.get("extra_steps", []):
            stype = step["step_type"]
            if stype == "click":
                page.click(step["selector"], timeout=3000)
            elif stype == "type":
                page.fill(step["selector"], step["text"], timeout=3000)
            elif stype == "wait":
                _time.sleep(step["timeout_ms"] / 1000)
            elif stype == "wait_selector":
                page.wait_for_selector(step["selector"], timeout=step["timeout_ms"])

        # Click submit
        page.click(flow["submit_button"], timeout=5000)

        # Wait for response
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        _time.sleep(2)

        # Check for failure indicators
        page_text = page.inner_text("body") if page.query_selector("body") else ""
        for failure in flow.get("failure_indicators", []):
            if failure.lower() in page_text.lower():
                raise Exception(f"Login failed: detected failure indicator '{failure}'")

        # Check for success indicators
        success_found = True
        if flow.get("success_indicators"):
            success_found = any(
                ind.lower() in page_text.lower()
                for ind in flow["success_indicators"]
            )

        result["success"] = success_found
        result["url"] = page.url
        result["title"] = page.title()
        result["error"] = None if success_found else "Login success indicators not found"

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["url"] = page.url
        result["title"] = page.title()
        try:
            ss = page.screenshot(full_page=False)
            result["screenshot"] = __import__("base64").b64encode(ss).decode()
        except Exception:
            pass

    print(json.dumps(result))
    browser.close()
"""


_MULTI_STEP_TEMPLATE = """
import sys
import json
import time as _time
from browser_use import Controller
from playwright.sync_api import sync_playwright

data_path = sys.argv[1] if len(sys.argv) > 1 else None
if data_path:
    with open(data_path) as f:
        data = json.load(f)
else:
    data = {}

steps = data.get("steps", [])
capture_screenshot = data.get("capture_screenshot", False)
capture_text = data.get("capture_text", False)

controller = Controller()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    results = []
    error = None

    try:
        for i, step in enumerate(steps):
            stype = step["step_type"]

            if stype == "navigate":
                page.goto(step["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

            elif stype == "click":
                page.click(step["selector"], timeout=5000)

            elif stype == "type":
                page.fill(step["selector"], step["text"], timeout=5000)

            elif stype == "press":
                page.press(step["selector"] or "body", step["keys"], timeout=3000)

            elif stype == "wait":
                _time.sleep(step["timeout_ms"] / 1000)

            elif stype == "wait_selector":
                page.wait_for_selector(step["selector"], timeout=step["timeout_ms"])

            elif stype == "wait_navigation":
                page.wait_for_load_state("domcontentloaded", timeout=step["timeout_ms"])

            elif stype == "select_dropdown":
                val = step.get("option_value") or step.get("option_label", "")
                if val:
                    page.select_option(step["selector"], value=val, timeout=3000)

            elif stype == "check":
                is_checked = page.is_checked(step["selector"], timeout=3000) if page.query_selector(step["selector"]) else False
                target = step.get("checked", True)
                if is_checked != target:
                    page.check(step["selector"], timeout=3000) if target else page.uncheck(step["selector"], timeout=3000)

            elif stype == "hover":
                page.hover(step["selector"], timeout=3000)

            elif stype == "screenshot":
                ss = page.screenshot(full_page=False)
                results.append({"step": i, "screenshot": __import__("base64").b64encode(ss).decode()})

            elif stype == "snapshot":
                html = page.content()
                results.append({"step": i, "html_length": len(html)})

            results.append({"step": i, "done": True})

    except Exception as e:
        error = str(e)
        try:
            ss = page.screenshot(full_page=False)
            results.append({"step": len(steps), "screenshot": __import__("base64").b64encode(ss).decode()})
        except Exception:
            pass

    final_text = None
    if capture_text:
        try:
            final_text = page.inner_text("body")
        except Exception:
            pass

    final_screenshot = None
    if capture_screenshot:
        try:
            ss = page.screenshot(full_page=False)
            final_screenshot = __import__("base64").b64encode(ss).decode()
        except Exception:
            pass

    output = {
        "success": error is None,
        "steps_completed": len(results),
        "total_steps": len(steps),
        "url": page.url,
        "title": page.title(),
        "error": error,
        "results": results,
        "captured_text": final_text,
        "screenshot": final_screenshot,
    }

    print(json.dumps(output))
    browser.close()
"""


# ------------------------------------------------------------------
# Execution Engine
# ------------------------------------------------------------------


class BrowserAutomation:
    """
    High-level browser automation using browser-use.

    All operations run via the isolated browser-use venv to avoid
    dependency conflicts with the main application.
    """

    def __init__(self, python_path: Optional[str] = None):
        self.python_path = python_path or _resolve_python()
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        """Check if browser-use automation is available."""
        if self._available is None:
            self._available = self._check_available()
        return self._available

    def _check_available(self) -> bool:
        """Check if the browser-use venv is functional."""
        try:
            result = subprocess.run(
                [self.python_path, "-c", "from browser_use import Controller; print('ok')"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except Exception:
            return False

    def _run_script(self, script_content: str, data: dict, timeout: int = 120) -> dict[str, Any]:
        """
        Execute a generated script via the browser-use venv.
        Data is written to a temp JSON file and passed as argv[1].
        """
        # Write script to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_browser_automation.py", delete=False
        ) as f:
            f.write(script_content)
            script_path = f.name

        # Write data to temp JSON file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_data.json", delete=False
        ) as f:
            json.dump(data, f)
            data_path = f.name

        try:
            result = subprocess.run(
                [self.python_path, script_path, data_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            # Try to parse JSON from stdout
            try:
                output = json.loads(stdout)
            except (json.JSONDecodeError, ValueError):
                output = {
                    "success": False,
                    "error": stdout or stderr or f"Script failed with code {result.returncode}",
                    "stderr": stderr,
                    "stdout": stdout,
                }

            if result.returncode != 0 and not output.get("success"):
                output.setdefault("error", stderr or stdout)
                output.setdefault("returncode", result.returncode)

            return output
        finally:
            Path(script_path).unlink(missing_ok=True)
            Path(data_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fill_form(
        self,
        url: str,
        fields: list[FormField],
        submit_selector: str,
        wait_for_selectors: Optional[list[str]] = None,
        screenshot_on_error: bool = True,
    ) -> AutomationResult:
        """
        Fill a web form and submit it.

        Args:
            url: The page URL to navigate to
            fields: List of FormField definitions
            submit_selector: CSS selector for the submit button
            wait_for_selectors: Selectors to wait for after submission
            screenshot_on_error: Capture screenshot on failure

        Returns:
            AutomationResult with success status and captured state
        """
        if not self.available:
            return AutomationResult(
                success=False,
                steps_completed=0,
                total_steps=len(fields) + 1,
                error="browser-use venv not available",
            )

        data = {
            "url": url,
            "fields": [f.to_dict() for f in fields],
            "submit_selector": submit_selector,
            "wait_for_selectors": wait_for_selectors or [],
            "screenshot_on_error": screenshot_on_error,
        }
        raw = self._run_script(_FORM_FILL_TEMPLATE, data)
        return AutomationResult(
            success=raw.get("success", False),
            steps_completed=raw.get("steps_completed", 0) if raw.get("success") else 0,
            total_steps=len(fields) + 1,
            screenshot=raw.get("screenshot"),
            error=raw.get("error"),
            final_url=raw.get("url"),
            final_title=raw.get("title"),
        )

    def run_login(self, login_flow: LoginFlow) -> AutomationResult:
        """
        Execute a complete login flow.

        Args:
            login_flow: Pre-configured LoginFlow definition

        Returns:
            AutomationResult with login outcome
        """
        if not self.available:
            return AutomationResult(
                success=False,
                steps_completed=0,
                total_steps=2 + len(login_flow.extra_steps),
                error="browser-use venv not available",
            )

        flow_data = {
            "name": login_flow.name,
            "url": login_flow.url,
            "username_field": login_flow.username_field,
            "password_field": login_flow.password_field,
            "username": login_flow.username,
            "password": login_flow.password,
            "submit_button": login_flow.submit_button,
            "success_indicators": login_flow.success_indicators,
            "failure_indicators": login_flow.failure_indicators,
            "extra_steps": [
                {
                    "step_type": s.step_type.value if isinstance(s.step_type, StepType) else s.step_type,
                    "selector": s.selector,
                    "text": s.text,
                    "timeout_ms": s.timeout_ms,
                }
                for s in login_flow.extra_steps
            ],
        }
        raw = self._run_script(_LOGIN_TEMPLATE, flow_data)
        return AutomationResult(
            success=raw.get("success", False),
            steps_completed=raw.get("steps_completed", 0) if raw.get("success") else 0,
            total_steps=2 + len(login_flow.extra_steps),
            screenshot=raw.get("screenshot"),
            error=raw.get("error"),
            final_url=raw.get("url"),
            final_title=raw.get("title"),
        )

    def run_sequence(
        self,
        steps: list[AutomationStep],
        capture_screenshot: bool = True,
        capture_text: bool = True,
    ) -> AutomationResult:
        """
        Execute a multi-step browser automation sequence.

        Args:
            steps: List of AutomationStep definitions
            capture_screenshot: Capture screenshot at end
            capture_text: Capture page text at end

        Returns:
            AutomationResult with execution outcome
        """
        if not self.available:
            return AutomationResult(
                success=False,
                steps_completed=0,
                total_steps=len(steps),
                error="browser-use venv not available",
            )

        steps_data = [
            {
                "step_type": s.step_type.value if isinstance(s.step_type, StepType) else s.step_type,
                "selector": s.selector,
                "text": s.text,
                "url": s.url,
                "timeout_ms": s.timeout_ms,
                "option_value": s.option_value,
                "option_label": s.option_label,
                "keys": s.keys,
                "checked": s.checked,
                "wait_for_url": s.wait_for_url,
            }
            for s in steps
        ]
        data = {
            "steps": steps_data,
            "capture_screenshot": capture_screenshot,
            "capture_text": capture_text,
        }
        raw = self._run_script(_MULTI_STEP_TEMPLATE, data, timeout=180)
        return AutomationResult(
            success=raw.get("success", False),
            steps_completed=raw.get("steps_completed", 0),
            total_steps=raw.get("total_steps", len(steps)),
            screenshot=raw.get("screenshot"),
            error=raw.get("error"),
            final_url=raw.get("url"),
            final_title=raw.get("title"),
            captured_text=raw.get("captured_text"),
            details={"step_results": raw.get("results", [])},
        )


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_automation: Optional[BrowserAutomation] = None


def get_automation() -> BrowserAutomation:
    """Get or create the global BrowserAutomation instance."""
    global _automation
    if _automation is None:
        _automation = BrowserAutomation()
    return _automation
