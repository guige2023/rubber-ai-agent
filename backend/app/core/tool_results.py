from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from pydantic_ai.messages import BinaryImage, ToolReturn


def _normalize_data(value: object) -> object:
    if hasattr(value, "model_dump"):
        value = value.model_dump()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): _normalize_data(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_normalize_data(item) for item in value]

    return str(value)


def build_tool_success_result(tool_name: str, raw_result: object) -> str | ToolReturn:
    if isinstance(raw_result, ToolReturn):
        normalized = _normalize_data(raw_result.return_value)
        payload = {"tool_name": tool_name, "result": normalized}
        return ToolReturn(
            return_value=json.dumps(payload, ensure_ascii=False, default=str),
            content=raw_result.content,
            metadata=raw_result.metadata,
        )

    if isinstance(raw_result, BinaryImage):
        payload = {
            "tool_name": tool_name,
            "result": {
                "kind": "binary_image",
                "media_type": raw_result.media_type,
                "identifier": raw_result.identifier,
            },
        }
        return ToolReturn(
            return_value=json.dumps(payload, ensure_ascii=False, default=str),
            content=[raw_result],
            metadata=payload,
        )

    normalized = _normalize_data(raw_result)
    payload = {"tool_name": tool_name, "result": normalized}
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_tool_error_result(
    tool_name: str,
    *,
    message: str,
    error_type: str,
    retryable: bool,
    summary: str | None = None,
    data: object = None,
) -> str:
    payload: dict[str, object] = {
        "tool_name": tool_name,
        "error": message,
    }
    if data is not None:
        payload["result"] = _normalize_data(data)
    return json.dumps(payload, ensure_ascii=False, default=str)
