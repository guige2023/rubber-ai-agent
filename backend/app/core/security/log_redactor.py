"""
P1-SEC-3: Log Redaction — structured log sanitization

Scrubs sensitive fields (bearer tokens, API keys, etc.) from log output
before it hits console or file handlers.

Usage:
    from app.core.security.log_redactor import RedactingFormatter, RedactingLogFilter

    # Apply to any logging handler
    handler.setFormatter(RedactingFormatter(original_format))

    # Or add as a filter on existing handlers
    handler.addFilter(RedactingLogFilter())
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any


# ── Patterns to redact ───────────────────────────────────────────────────────

_REDACT_MARKER = "[REDACTED]"

# Patterns matched against field names (case-insensitive)
_SENSITIVE_NAME_PATTERNS = [
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*bearer.*", re.IGNORECASE),
    re.compile(r".*auth.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*private[_-]?key.*", re.IGNORECASE),
    re.compile(r".*session[_-]?id.*", re.IGNORECASE),
    re.compile(r".*access[_-]?token.*", re.IGNORECASE),
    re.compile(r".*refresh[_-]?token.*", re.IGNORECASE),
]

# Patterns matched against raw log text (not just JSON fields)
_TEXT_PATTERNS = [
    # Bearer token format
    re.compile(r"(Bearer\s+)([A-Za-z0-9_\-\.]{10,})", re.IGNORECASE),
    # OpenAI / Anthropic API key formats
    re.compile(r"(sk[-_]?)([A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(sk[-_]?ant[A-Za-z0-9_\-]{30,})", re.IGNORECASE),
    # Generic hex/key-like strings in auth headers
    re.compile(r"([\"'][A-Za-z_]+[_\-]?[Kk]ey[\"']\s*[:=]\s*[\"'])([A-Za-z0-9_\-]{16,}[\"'])", re.IGNORECASE),
]


def _is_sensitive_name(key: str) -> bool:
    return any(p.match(key) for p in _SENSITIVE_NAME_PATTERNS)


def _scrub_text(text: str) -> str:
    """Scrub sensitive patterns from raw text."""
    result = text
    for pattern in _TEXT_PATTERNS:
        result = pattern.sub(lambda m: m.group(1) + _REDACT_MARKER, result)
    return result


def _scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub a dict, redacting sensitive values by key name."""
    if not isinstance(data, dict):
        return data

    result: dict[str, Any] = {}
    for key, value in data.items():
        if _is_sensitive_name(key):
            result[key] = _REDACT_MARKER
        elif isinstance(value, dict):
            result[key] = _scrub_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _scrub_dict(v) if isinstance(v, dict) else _REDACT_MARKER if _is_sensitive_name(str(v)) else v
                for v in value
            ]
        elif isinstance(value, str):
            # Scrub any text patterns in string values too
            result[key] = _scrub_text(value)
        else:
            result[key] = value
    return result


# ── Formatter ────────────────────────────────────────────────────────────────

class RedactingFormatter(logging.Formatter):
    """
    Logging formatter that scrubs sensitive fields before output.

    Handles both plain-text log records and JSON-encoded records
    (when used with pythonjsonlogger.orjson.OrjsonFormatter).
    """

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # Scrub the message and any extra dict attached to the record
        raw_msg = record.getMessage()

        # Try to parse as JSON (from OrjsonFormatter)
        try:
            parsed = json.loads(raw_msg)
            if isinstance(parsed, dict):
                # Scrub the entire parsed object
                scrubbed = _scrub_dict(parsed)
                record.msg = json.dumps(scrubbed, ensure_ascii=False)
                record.args = ()  # Clear args so Formatter doesn't re-substitute
        except (json.JSONDecodeError, TypeError):
            # Plain text — just scrub patterns
            record.msg = _scrub_text(raw_msg)

        # Scrub extra fields added via `extra={...}`
        if hasattr(record, "__dict__"):
            for key in list(record.__dict__.keys()):
                if _is_sensitive_name(key):
                    setattr(record, key, _REDACT_MARKER)

        return super().format(record)


class RedactingLogFilter(logging.Filter):
    """
    Log filter that drops records containing only sensitive data
    or scrubs in-place.

    Can be added to any handler via `handler.addFilter(RedactingLogFilter())`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _scrub_text(str(record.msg))

        if hasattr(record, "args"):
            record.args = tuple(
                _scrub_text(str(a)) if isinstance(a, str) else a
                for a in record.args
            )

        return True


# ── Patch dictConfig to inject redaction ───────────────────────────────────

def patch_dict_config_logging() -> None:
    """
    Monkey-patch the logging configuration to inject redaction filters
    into all existing handlers.

    Call this once after `configure_logging()` in main.py:
        from app.core.security.log_redactor import patch_dict_config_logging
        patch_dict_config_logging()
    """
    root = logging.getLogger()
    for handler in root.handlers:
        # Insert redaction formatter (preserve existing format)
        old_fmt = handler.formatter
        if old_fmt is None:
            fmt_str = "%(asctime)s %(levelname)s %(name)s: %(message)s"
        else:
            fmt_str = getattr(old_fmt, "_fmt", "%(message)s")
        handler.setFormatter(RedactingFormatter(fmt_str))
        # Don't add duplicate filters
        if not any(isinstance(f, RedactingLogFilter) for f in handler.filters):
            handler.addFilter(RedactingLogFilter())
