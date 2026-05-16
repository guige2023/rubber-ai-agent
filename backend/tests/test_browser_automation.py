"""
Tests for browser_automation.py - high-level browser automation wrappers.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.core.browser_automation import (
    AutomationResult,
    AutomationStep,
    BrowserAutomation,
    FormField,
    LoginFlow,
    StepType,
    _FORM_FILL_TEMPLATE,
    _LOGIN_TEMPLATE,
    _MULTI_STEP_TEMPLATE,
)


class TestFormFieldSerialization:
    def test_form_field_to_dict(self):
        f = FormField(selector="input#username", value="user@example.com", field_type="email")
        d = f.to_dict()
        assert d["selector"] == "input#username"
        assert d["value"] == "user@example.com"
        assert d["field_type"] == "email"

    def test_form_field_defaults(self):
        f = FormField(selector="input#password", value="secret")
        assert f.field_type == "text"


class TestStepTypeEnum:
    def test_step_type_values(self):
        assert StepType.NAVIGATE == "navigate"
        assert StepType.CLICK == "click"
        assert StepType.TYPE == "type"
        assert StepType.WAIT == "wait"
        assert StepType.SCREENSHOT == "screenshot"


class TestAutomationStep:
    def test_navigate_step(self):
        step = AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com")
        assert step.step_type == StepType.NAVIGATE
        assert step.url == "https://example.com"

    def test_click_step(self):
        step = AutomationStep(step_type=StepType.CLICK, selector="#submit-btn")
        assert step.selector == "#submit-btn"

    def test_type_step(self):
        step = AutomationStep(step_type=StepType.TYPE, selector="input#name", text="Alice")
        assert step.text == "Alice"

    def test_wait_step(self):
        step = AutomationStep(step_type=StepType.WAIT, timeout_ms=3000)
        assert step.timeout_ms == 3000

    def test_select_dropdown(self):
        step = AutomationStep(step_type=StepType.SELECT_DROPDOWN, selector="select#country", option_value="CN")
        assert step.option_value == "CN"


class TestLoginFlow:
    def test_login_flow_basic(self):
        flow = LoginFlow(
            name="test-login",
            url="https://app.example.com/login",
            username_field="#username",
            password_field="#password",
            username="admin",
            password="secret123",
            submit_button="#login-btn",
        )
        assert flow.name == "test-login"
        assert flow.username == "admin"
        assert len(flow.extra_steps) == 0

    def test_login_flow_with_extra_steps(self):
        flow = LoginFlow(
            name="github-login",
            url="https://github.com/login",
            username_field="#login_field",
            password_field="#password",
            username="user",
            password="pass",
            submit_button="button[type='submit']",
            extra_steps=[
                AutomationStep(step_type=StepType.CLICK, selector="#accept-terms"),
            ],
        )
        assert len(flow.extra_steps) == 1
        assert flow.extra_steps[0].step_type == StepType.CLICK


class TestTemplates:
    """Test that script templates are valid Python and contain expected structure."""

    def test_form_fill_template_valid_syntax(self):
        compile(_FORM_FILL_TEMPLATE, "<string>", "exec")

    def test_form_fill_template_has_navigate(self):
        assert "page.goto" in _FORM_FILL_TEMPLATE

    def test_form_fill_template_has_fill(self):
        assert "page.fill" in _FORM_FILL_TEMPLATE

    def test_form_fill_template_has_click(self):
        assert "page.click" in _FORM_FILL_TEMPLATE

    def test_form_fill_template_reads_data_from_file(self):
        assert "sys.argv[1]" in _FORM_FILL_TEMPLATE
        assert "json.load" in _FORM_FILL_TEMPLATE

    def test_login_template_valid_syntax(self):
        compile(_LOGIN_TEMPLATE, "<string>", "exec")

    def test_login_template_has_fill(self):
        assert "page.fill" in _LOGIN_TEMPLATE

    def test_login_template_checks_failure(self):
        assert "failure_indicators" in _LOGIN_TEMPLATE

    def test_login_template_reads_data_from_file(self):
        assert "sys.argv[1]" in _LOGIN_TEMPLATE

    def test_multi_step_template_valid_syntax(self):
        compile(_MULTI_STEP_TEMPLATE, "<string>", "exec")

    def test_multi_step_template_has_all_step_types(self):
        for stype in ["navigate", "click", "type", "wait", "screenshot", "hover", "check"]:
            assert stype in _MULTI_STEP_TEMPLATE

    def test_multi_step_template_reads_data_from_file(self):
        assert "sys.argv[1]" in _MULTI_STEP_TEMPLATE


class TestFormFieldIntegration:
    """Test that form field definitions round-trip correctly."""

    def test_all_field_types_serialize(self):
        types = ["text", "password", "email", "checkbox", "select"]
        for ft in types:
            f = FormField(selector=f"#{ft}", value="val", field_type=ft)
            d = f.to_dict()
            assert d["field_type"] == ft


class TestAutomationResult:
    def test_to_dict_full(self):
        result = AutomationResult(
            success=True,
            steps_completed=5,
            total_steps=5,
            screenshot="base64data",
            final_url="https://example.com/done",
            final_title="Done",
            captured_text="Page content",
            details={"key": "value"},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["steps_completed"] == 5
        assert d["final_url"] == "https://example.com/done"

    def test_to_dict_minimal(self):
        result = AutomationResult(success=False, steps_completed=2, total_steps=5, error="boom")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "boom"
        assert d["steps_completed"] == 2


class TestBrowserAutomationInit:
    def test_default_python_path(self):
        from app.core import browser_automation as ba

        assert ba.BROWSER_USE_PYTHON == os.path.expanduser("~/.venv/browser-use/bin/python")

    def test_resolve_python_fallback(self):
        from app.core import browser_automation as ba

        # _resolve_python() returns BROWSER_USE_PYTHON if it exists,
        # otherwise falls back to SYSTEM_PYTHON
        original = ba.BROWSER_USE_PYTHON
        try:
            # Simulate venv doesn't exist -> should use SYSTEM_PYTHON
            ba.BROWSER_USE_PYTHON = "/nonexistent/python"
            resolved = ba._resolve_python()
            assert resolved == ba.SYSTEM_PYTHON
        finally:
            ba.BROWSER_USE_PYTHON = original


class TestBrowserAutomationUnavailable:
    """Test behavior when browser-use is not available."""

    def test_fill_form_unavailable(self):
        ba = BrowserAutomation()
        ba._available = False

        result = ba.fill_form(
            url="https://example.com",
            fields=[FormField(selector="#a", value="b")],
            submit_selector="#btn",
        )
        assert result.success is False
        assert "not available" in result.error

    def test_run_login_unavailable(self):
        ba = BrowserAutomation()
        ba._available = False

        flow = LoginFlow(
            name="test",
            url="https://example.com",
            username_field="#u",
            password_field="#p",
            username="u",
            password="p",
            submit_button="#btn",
        )
        result = ba.run_login(flow)
        assert result.success is False
        assert "not available" in result.error

    def test_run_sequence_unavailable(self):
        ba = BrowserAutomation()
        ba._available = False

        steps = [AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com")]
        result = ba.run_sequence(steps)
        assert result.success is False
        assert "not available" in result.error


class TestDataFilePassing:
    """Verify scripts read data from the JSON file correctly."""

    def test_form_fill_data_includes_url(self):
        fields = [FormField(selector="#a", value="b")]
        data = {
            "url": "https://example.com/form",
            "fields": [f.to_dict() for f in fields],
            "submit_selector": "#btn",
            "wait_for_selectors": [],
            "screenshot_on_error": True,
        }
        # Write and re-read to confirm round-trip
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            with open(path) as f:
                loaded = json.load(f)
            assert loaded["url"] == "https://example.com/form"
            assert len(loaded["fields"]) == 1
        finally:
            Path(path).unlink(missing_ok=True)

    def test_login_flow_data_serializable(self):
        flow = LoginFlow(
            name="test",
            url="https://example.com",
            username_field="#u",
            password_field="#p",
            username="myuser",
            password="mypassword",
            submit_button="#btn",
            success_indicators=["Dashboard", "Welcome"],
            failure_indicators=["Invalid", "locked"],
        )
        flow_data = {
            "name": flow.name,
            "url": flow.url,
            "username_field": flow.username_field,
            "password_field": flow.password_field,
            "username": flow.username,
            "password": flow.password,
            "submit_button": flow.submit_button,
            "success_indicators": flow.success_indicators,
            "failure_indicators": flow.failure_indicators,
            "extra_steps": [
                {
                    "step_type": s.step_type.value,
                    "selector": s.selector,
                    "text": s.text,
                    "timeout_ms": s.timeout_ms,
                }
                for s in flow.extra_steps
            ],
        }
        # Verify it's serializable
        json_str = json.dumps(flow_data)
        parsed = json.loads(json_str)
        assert parsed["username"] == "myuser"
        assert parsed["success_indicators"] == ["Dashboard", "Welcome"]

    def test_multi_step_data_serializable(self):
        steps = [
            AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com"),
            AutomationStep(step_type=StepType.CLICK, selector="#next"),
            AutomationStep(step_type=StepType.TYPE, selector="#search", text="query"),
            AutomationStep(step_type=StepType.WAIT, timeout_ms=1000),
        ]
        steps_data = [
            {
                "step_type": s.step_type.value,
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
        json_str = json.dumps(steps_data)
        parsed = json.loads(json_str)
        assert len(parsed) == 4
        assert parsed[0]["step_type"] == "navigate"
        assert parsed[1]["step_type"] == "click"
