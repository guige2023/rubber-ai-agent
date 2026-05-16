"""
Tests for browser_automation.py - high-level browser automation wrappers.
"""

import json
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
    _escape_py_string,
    _generate_form_fill_script,
    _generate_login_script,
    _generate_multi_step_script,
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


class TestEscapePyString:
    def test_escape_simple(self):
        assert _escape_py_string("hello") == "hello"

    def test_escape_quotes(self):
        assert _escape_py_string('say "hello"') == r"say \"hello\""

    def test_escape_newline(self):
        assert _escape_py_string("line1\nline2") == r"line1\nline2"

    def test_escape_backslash(self):
        assert _escape_py_string(r"path\to\file") == r"path\to\file"


class TestGenerateFormFillScript:
    def test_generates_valid_python_syntax(self):
        fields = [
            FormField(selector="#username", value="alice"),
            FormField(selector="#password", value="secret", field_type="password"),
        ]
        script = _generate_form_fill_script(
            url="https://example.com/form",
            fields=fields,
            submit_selector="#submit",
        )
        # Should be valid Python (compile check)
        compile(script, "<string>", "exec")

    def test_script_contains_navigate(self):
        script = _generate_form_fill_script(
            url="https://example.com/form",
            fields=[],
            submit_selector="#submit",
        )
        assert "page.goto" in script
        assert "example.com/form" in script

    def test_script_fills_fields(self):
        fields = [
            FormField(selector="#email", value="a@b.com"),
        ]
        script = _generate_form_fill_script(
            url="https://example.com",
            fields=fields,
            submit_selector="#btn",
        )
        assert 'page.fill("#email"' in script
        assert "a@b.com" in script

    def test_script_clicks_submit(self):
        script = _generate_form_fill_script(
            url="https://example.com",
            fields=[],
            submit_selector="#my-button",
        )
        assert 'page.click("#my-button"' in script

    def test_script_handles_checkbox(self):
        fields = [FormField(selector="#agree", value="", field_type="checkbox")]
        script = _generate_form_fill_script(
            url="https://example.com",
            fields=fields,
            submit_selector="#submit",
        )
        assert "checkbox" in script.lower()
        assert 'page.check("#agree"' in script or "is_checked" in script


class TestGenerateLoginScript:
    def test_generates_valid_python(self):
        flow = LoginFlow(
            name="test",
            url="https://example.com/login",
            username_field="#user",
            password_field="#pass",
            username="u",
            password="p",
            submit_button="#btn",
        )
        script = _generate_login_script(flow)
        compile(script, "<string>", "exec")

    def test_script_fills_credentials(self):
        flow = LoginFlow(
            name="secure-login",
            url="https://secure.example.com/login",
            username_field="input[name='username']",
            password_field="input[name='password']",
            username="myuser",
            password="mypassword",
            submit_button="button[type='submit']",
        )
        script = _generate_login_script(flow)
        assert "myuser" in script
        assert "mypassword" in script
        assert "input[name='username']" in script

    def test_script_checks_failure_indicators(self):
        flow = LoginFlow(
            name="test",
            url="https://example.com",
            username_field="#u",
            password_field="#p",
            username="u",
            password="p",
            submit_button="#btn",
            failure_indicators=["Invalid credentials", "Account locked"],
        )
        script = _generate_login_script(flow)
        assert "Invalid credentials" in script
        assert "failure_indicators" in script

    def test_extra_steps_included(self):
        flow = LoginFlow(
            name="test",
            url="https://example.com",
            username_field="#u",
            password_field="#p",
            username="u",
            password="p",
            submit_button="#btn",
            extra_steps=[
                AutomationStep(step_type=StepType.CLICK, selector="#accept"),
                AutomationStep(step_type=StepType.WAIT, timeout_ms=1000),
            ],
        )
        script = _generate_login_script(flow)
        assert 'page.click("#accept")' in script
        assert "time.sleep" in script


class TestGenerateMultiStepScript:
    def test_generates_valid_python(self):
        steps = [
            AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com"),
            AutomationStep(step_type=StepType.CLICK, selector="a.next"),
        ]
        script = _generate_multi_step_script(steps)
        compile(script, "<string>", "exec")

    def test_navigate_step(self):
        steps = [AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com")]
        script = _generate_multi_step_script(steps)
        assert "navigate" in script
        assert "example.com" in script

    def test_click_step(self):
        steps = [AutomationStep(step_type=StepType.CLICK, selector="#btn")]
        script = _generate_multi_step_script(steps)
        assert 'page.click("#btn")' in script

    def test_type_step(self):
        steps = [AutomationStep(step_type=StepType.TYPE, selector="#search", text="query")]
        script = _generate_multi_step_script(steps)
        assert "query" in script

    def test_wait_step(self):
        steps = [AutomationStep(step_type=StepType.WAIT, timeout_ms=2000)]
        script = _generate_multi_step_script(steps)
        assert "time.sleep" in script
        assert "2" in script  # 2000ms = 2s

    def test_wait_selector_step(self):
        steps = [AutomationStep(step_type=StepType.WAIT_SELECTOR, selector="#loaded", timeout_ms=5000)]
        script = _generate_multi_step_script(steps)
        assert "wait_for_selector" in script
        assert "#loaded" in script

    def test_select_dropdown_step(self):
        steps = [AutomationStep(step_type=StepType.SELECT_DROPDOWN, selector="select#country", option_value="CN")]
        script = _generate_multi_step_script(steps)
        assert "select_option" in script
        assert "CN" in script

    def test_check_step(self):
        steps = [AutomationStep(step_type=StepType.CHECK, selector="#agree", checked=True)]
        script = _generate_multi_step_script(steps)
        assert "check" in script.lower()

    def test_hover_step(self):
        steps = [AutomationStep(step_type=StepType.HOVER, selector=".tooltip-trigger")]
        script = _generate_multi_step_script(steps)
        assert "hover" in script

    def test_screenshot_step(self):
        steps = [AutomationStep(step_type=StepType.SCREENSHOT)]
        script = _generate_multi_step_script(steps, capture_screenshot=True)
        assert "screenshot" in script
        assert "base64" in script

    def test_snapshot_step(self):
        steps = [AutomationStep(step_type=StepType.SNAPSHOT)]
        script = _generate_multi_step_script(steps, capture_text=True)
        assert "inner_text" in script

    def test_press_step(self):
        steps = [AutomationStep(step_type=StepType.PRESS, keys="Enter")]
        script = _generate_multi_step_script(steps)
        assert "press" in script
        assert "Enter" in script

    def test_multiple_steps(self):
        steps = [
            AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com"),
            AutomationStep(step_type=StepType.CLICK, selector="#btn"),
            AutomationStep(step_type=StepType.TYPE, selector="#input", text="hello"),
            AutomationStep(step_type=StepType.WAIT, timeout_ms=500),
        ]
        script = _generate_multi_step_script(steps)
        assert steps[0].url in script
        assert 'page.click("#btn")' in script
        assert "hello" in script


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
    def test_resolves_python_path(self):
        import app.core.browser_automation as ba

        # Should default to browser-use venv
        assert ba.BROWSER_USE_PYTHON == os.path.expanduser("~/.venv/browser-use/bin/python")

    def test_python_exists_check(self):
        # If browser-use venv exists, path should resolve
        ba = BrowserAutomation()
        python_exists = Path(ba.python_path).exists()
        # available may be True or False depending on whether the venv is set up
        assert python_exists or not ba.available


class TestBrowserAutomationFillForm:
    def test_unavailable_returns_error_result(self):
        ba = BrowserAutomation()
        # Mock unavailable
        ba._available = False

        result = ba.fill_form(
            url="https://example.com",
            fields=[FormField(selector="#a", value="b")],
            submit_selector="#btn",
        )
        assert result.success is False
        assert "not available" in result.error


class TestBrowserAutomationRunLogin:
    def test_unavailable_returns_error_result(self):
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


class TestBrowserAutomationRunSequence:
    def test_unavailable_returns_error_result(self):
        ba = BrowserAutomation()
        ba._available = False

        steps = [AutomationStep(step_type=StepType.NAVIGATE, url="https://example.com")]
        result = ba.run_sequence(steps)
        assert result.success is False
        assert "not available" in result.error


import os
from pathlib import Path
