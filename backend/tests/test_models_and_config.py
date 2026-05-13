from datetime import date, datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from urllib.error import HTTPError

import pytest
from sqlmodel import select, Session as DBSession

import app.core.db as db_module
from app.models.database import SessionModel, MessageModel, TaskModel, AppConfigModel
from app.models.schemas import (
    AgentRunResult,
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcErrorResponse,
    MCPToolModel,
    MessageSchema,
    ScheduleSchema,
    SessionCompactionMemory,
    SessionMemory,
    SessionSchema,
    SessionResponseSchema,
    SkillModel,
    TaskSchema,
    TaskStatus,
    Usage,
    ValidatorBaseModel,
)
from app.core.config import Settings as config
from app.core.model_manager import ModelListEndpointUnavailable, ModelManager

from app.models.events import (
    FerrymanEventEnvelope,
    EventNamespace,
    ToolActivityPayload,
    ToolPhase,
    ChatFinalPayload,
    RefreshPayload,
    EntityAction,
    DataEntity
)


def test_app_config_crud(session):
    """Test AppConfig database operations."""
    app_config = AppConfigModel(key="test.key", value={"foo": "bar"}, category="test")
    session.add(app_config)
    session.commit()
    
    statement = select(AppConfigModel).where(AppConfigModel.key == "test.key")
    result = session.exec(statement).first()
    assert result is not None
    assert result.value == {"foo": "bar"}
    assert result.category == "test"


def test_session_message_relationship(session):
    """Test creating a session and associated messages."""
    new_session = SessionModel(title="Test Session")
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    
    msg = MessageModel(
        session_id=new_session.id,
        role="user",
        content="Hello",
        type="text"
    )
    session.add(msg)
    session.commit()
    
    statement = select(MessageModel).where(MessageModel.session_id == new_session.id)
    results = session.exec(statement).all()
    assert len(results) == 1
    assert results[0].content == "Hello"


def test_migrate_session_memory_json_payloads_clears_legacy_text(session):
    legacy_session = SessionModel(title="Legacy Session", memory=None)
    session.add(legacy_session)
    session.commit()
    session.refresh(legacy_session)

    with db_module.engine.connect() as conn:
        conn.exec_driver_sql(
            "UPDATE sessions SET memory = ? WHERE id = ?",
            ("legacy note text", legacy_session.id),
        )
        conn.commit()

    db_module.migrate_session_memory_json_payloads()

    with DBSession(db_module.engine) as verify_session:
        refreshed = verify_session.get(SessionModel, legacy_session.id)
        assert refreshed is not None
        assert refreshed.memory is None


def test_pydantic_schema_validation():
    """Test Pydantic model validation and transformation."""
    data = {
        "id": "test-uuid",
        "session_id": "session-uuid",
        "role": "assistant",
        "content": "Hi",
        "type": "text",
        "created_at": datetime.now(timezone.utc)
    }
    model = MessageSchema(**data)
    assert model.role == "assistant"
    assert model.content == "Hi"


def test_session_model_includes_usage_metadata_and_normalizes_datetimes():
    model = SessionSchema.model_validate({
        "id": "session-1",
        "title": "SEO Matrix",
        "memory": {"schema_version": 1},
        "metadata": {"kind": "schedule"},
        "input_tokens": 11,
        "output_tokens": 5,
        "created_at": "2026-04-16T12:00:00+08:00",
        "updated_at": datetime(2026, 4, 16, 4, 5, tzinfo=timezone.utc),
    })

    assert model.input_tokens == 11
    assert model.output_tokens == 5
    assert model.created_at == datetime(2026, 4, 16, 4, 0, tzinfo=timezone.utc)
    assert model.updated_at == datetime(2026, 4, 16, 4, 5, tzinfo=timezone.utc)
    assert model.model_dump(mode="json")["created_at"] == "2026-04-16T04:00:00Z"
    assert "active_run" not in model.model_dump(mode="json")


def test_session_response_model_adds_runtime_active_run():
    model = SessionResponseSchema.model_validate({
        "id": "session-1",
        "title": "SEO Matrix",
        "metadata": {},
        "input_tokens": 11,
        "output_tokens": 5,
        "active_run": {"run_id": "run-1", "status": "running"},
        "created_at": "2026-04-16T12:00:00+08:00",
        "updated_at": "2026-04-16T12:05:00+08:00",
    })

    dumped = model.model_dump(mode="json")
    assert dumped["active_run"] == {"run_id": "run-1", "status": "running"}
    assert dumped["created_at"] == "2026-04-16T04:00:00Z"


def test_response_schema_datetime_fields_are_normalized_to_utc():
    message = MessageSchema.model_validate({
        "id": "message-1",
        "session_id": "session-1",
        "role": "assistant",
        "content": "Done",
        "type": "text",
        "created_at": "2026-04-16T12:00:00+08:00",
    })
    task = TaskSchema.model_validate({
        "id": "task-1",
        "session_id": "session-1",
        "title": "Task",
        "created_at": "2026-04-16T12:00:00+08:00",
        "updated_at": "2026-04-16T12:05:00+08:00",
        "finished_at": "2026-04-16T12:10:00+08:00",
    })
    schedule = ScheduleSchema.model_validate({
        "id": "schedule-1",
        "name": "Daily",
        "cron_expression": "0 0 * * *",
        "last_run_at": "2026-04-16T12:00:00+08:00",
        "next_run_at": "2026-04-17T12:00:00+08:00",
        "created_at": "2026-04-16T11:00:00+08:00",
        "updated_at": "2026-04-16T11:30:00+08:00",
    })

    assert message.created_at == datetime(2026, 4, 16, 4, 0, tzinfo=timezone.utc)
    assert task.finished_at == datetime(2026, 4, 16, 4, 10, tzinfo=timezone.utc)
    assert schedule.next_run_at == datetime(2026, 4, 17, 4, 0, tzinfo=timezone.utc)

    assert message.model_dump(mode="json")["created_at"] == "2026-04-16T04:00:00Z"
    assert task.model_dump(mode="json")["finished_at"] == "2026-04-16T04:10:00Z"
    assert schedule.model_dump(mode="json")["next_run_at"] == "2026-04-17T04:00:00Z"


def test_all_schema_models_validate_defaults_and_json_payloads():
    skill = SkillModel.model_validate({
        "name": "seo-keyword-research",
        "description": "Find SEO keywords.",
        "path": Path("/tmp/skill"),
        "created": date(2026, 5, 1),
        "updated": date(2026, 5, 2),
    })
    assert skill.version == "0.1.0"
    assert skill.author == "Unknown"
    assert skill.model_dump(mode="json")["path"] == "/tmp/skill"

    mcp_tool = MCPToolModel.model_validate({
        "name": "navigate",
        "description": "Open a URL.",
        "arguments": {"url": "https://example.com"},
        "server_name": "browser",
    })
    assert mcp_tool.arguments["url"] == "https://example.com"

    compaction = SessionCompactionMemory.model_validate({
        "summary": "  compacted  ",
        "cutoff_created_at": "2026-05-10T16:00:00+08:00",
    })
    assert compaction.summary == "compacted"
    assert compaction.cutoff_created_at == datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc)

    assert TaskSchema.model_validate({
        "id": "task-default-status",
        "session_id": "session-1",
        "title": "Task",
        "created_at": "2026-05-10T08:00:00Z",
        "updated_at": "2026-05-10T08:00:00Z",
    }).status == TaskStatus.PENDING

    assert ScheduleSchema.model_validate({
        "id": "schedule-defaults",
        "name": "Daily",
        "cron_expression": "0 0 * * *",
        "created_at": "2026-05-10T08:00:00Z",
        "updated_at": "2026-05-10T08:00:00Z",
    }).enabled is True

    usage = Usage(input_tokens=3, output_tokens=4)
    assert usage.total_tokens == 0

    run_result = AgentRunResult(status="success", session_id="session-1", usage=usage)
    assert run_result.model_dump(mode="json")["usage"] == {
        "input_tokens": 3,
        "output_tokens": 4,
        "total_tokens": 0,
    }

    rpc_error = JsonRpcError(code=JsonRpcErrorCode.INVALID_PARAMS, message="Invalid params")
    rpc_response = JsonRpcErrorResponse(error=rpc_error, id=12)
    assert rpc_response.model_dump(mode="json") == {
        "jsonrpc": "2.0",
        "error": {"code": -32602, "message": "Invalid params"},
        "id": 12,
    }


def test_validator_base_model_utc_datetime_normalizes_naive_and_aware_values():
    naive = datetime(2026, 5, 10, 8, 0)
    aware = datetime(2026, 5, 10, 16, 0, tzinfo=timezone.utc)

    assert ValidatorBaseModel.utc_datetime(None) is None
    assert ValidatorBaseModel.utc_datetime(naive) == datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc)
    assert ValidatorBaseModel.utc_datetime(aware) == aware


def test_session_memory_schema_normalizes_compaction_payload():
    memory = SessionMemory.model_validate(
        {
            "schema_version": 1,
            "unknown": "ignored",
            "compaction": {
                "summary": "  compressed history  ",
                "cutoff_created_at": "2026-04-16T12:00:00+08:00",
                "updated_at": datetime(2026, 4, 16, 4, 5, tzinfo=timezone.utc),
                    "extra": "ignored",
            },
        }
    )

    assert memory.model_dump(mode="json", exclude_none=True) == {
        "schema_version": 1,
        "compaction": {
            "summary": "compressed history",
            "cutoff_created_at": "2026-04-16T04:00:00Z",
            "updated_at": "2026-04-16T04:05:00Z",
        },
    }


def test_session_memory_schema_tolerates_legacy_shape_mismatches():
    memory = SessionMemory.model_validate(
        {
            "schema_version": 99,
            "compaction": "legacy freeform memory",
        }
    )

    assert memory.model_dump(mode="json", exclude_none=True) == {
        "schema_version": 1,
        "compaction": {},
    }


def test_event_models_serialization():
    """Test that event models can be created and serialized properly."""
    tool_payload = ToolActivityPayload(
        run_id="run-1",
        tool_name="navigate",
        phase=ToolPhase.START,
        input={"url": "example.com"}
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="tool_activity",
        session_id="session-1",
        payload=tool_payload
    )
    
    dumped = env.model_dump(mode="json")
    assert dumped["namespace"] == "agent"
    assert dumped["payload"]["phase"] == "start"
    assert dumped["payload"]["input"]["url"] == "example.com"
    assert "ts" in dumped

    chat_payload = ChatFinalPayload(
        run_id="run-2",
        messages=[{"role": "assistant", "content": "Done"}],
        usage={"input_tokens": 10, "output_tokens": 5}
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="chat_final",
        payload=chat_payload
    )
    dumped = env.model_dump(mode="json")
    assert dumped["payload"]["messages"][0]["content"] == "Done"

    refresh_payload = RefreshPayload(
        entity=DataEntity.TASK,
        action=EntityAction.UPDATED,
        entity_id="task-123"
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.DATA,
        event="refresh",
        payload=refresh_payload
    )
    dumped = env.model_dump(mode="json")
    assert dumped["payload"]["entity"] == "task"


def test_config_registry_persistence(session):
    """Test config registry sets and gets via the database."""
    test_key = "registry.test.key"
    test_val = {"enabled": True, "count": 42}
    
    config.set(test_key, test_val, category="test")
    retrieved = config.get(test_key)
    assert retrieved == test_val
    
    from app.core.db import get_session
    with get_session() as db_session:
         statement = select(AppConfigModel).where(AppConfigModel.key == test_key)
         record = db_session.exec(statement).first()
         assert record is not None
         assert record.value == test_val


def test_config_list_by_category():
    """Test filtering configurations by category."""
    config.set("cat.1", "val1", category="c1")
    config.set("cat.2", "val2", category="c1")
    config.set("cat.3", "val3", category="c2")
    
    c1_list = config.list_by_category("c1")
    assert len(c1_list) >= 2
    keys = [item.key for item in c1_list]
    assert "cat.1" in keys
    assert "cat.2" in keys
    assert "cat.3" not in keys


def test_available_models_include_qwen_and_dynamic_custom_model():
    """Configured providers should be fetched online and custom models remain selectable."""
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("llm.qwen", {"api_key": "sk-qwen"}, category="llm")
    config.set("llm.deepseek", {"api_key": "sk-deepseek"}, category="llm")
    config.set("llm.kimi", {"api_key": "sk-kimi"}, category="llm")
    config.set(
        "llm.custom",
        {"api_key": "sk-custom", "base_url": "https://custom.example.com/v1", "model": "my-custom-model"},
        category="llm",
    )
    config.set("system.llm.active_model", "qwen:qwen-plus", category="system")

    original_fetcher = ModelManager._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o", "text-embedding-3-large"]
        if provider == "qwen":
            raise ModelListEndpointUnavailable("HTTP 404")
        if provider == "deepseek":
            return ["deepseek-v4-pro", "deepseek-v4-flash"]
        if provider == "kimi":
            return ["kimi-k2.5", "kimi-k2-thinking"]
        return []

    ModelManager._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = ModelManager(config()).get_available_models()
    finally:
        ModelManager._fetch_provider_models = original_fetcher

    assert "openai" in models
    assert "gemini" not in models
    assert models["openai"] == ["gpt-4o", "text-embedding-3-large"]
    assert "qwen" not in models
    assert "deepseek" in models
    assert "kimi" in models
    assert models["deepseek"] == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert "custom" in models
    assert models["kimi"] == ["kimi-k2.5", "kimi-k2-thinking"]
    assert models["custom"] == ["my-custom-model"]


def test_llm_provider_catalog_preserves_settings_display_order():
    assert list(ModelManager.get_llm_provider_catalog()) == [
        "kimi",
        "gemini",
        "deepseek",
        "qwen",
        "openai",
        "anthropic",
        "custom",
    ]


def test_available_models_include_openai_anthropic_and_gemini_when_configured():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("llm.anthropic", {"api_key": "sk-anthropic"}, category="llm")
    config.set("llm.gemini", {"api_key": "sk-gemini"}, category="llm")
    config.set("system.llm.active_model", "openai:gpt-4o", category="system")

    original_fetcher = ModelManager._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o", "text-embedding-3-large"]
        if provider == "anthropic":
            return ["claude-sonnet-4-5", "claude-opus-4-1"]
        if provider == "gemini":
            return ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview"]
        return []

    ModelManager._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = ModelManager(config()).get_available_models()
    finally:
        ModelManager._fetch_provider_models = original_fetcher

    assert models["openai"] == ["gpt-4o", "text-embedding-3-large"]
    assert models["anthropic"] == ["claude-sonnet-4-5", "claude-opus-4-1"]
    assert models["gemini"] == ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview"]


def test_get_available_models_hides_unconfigured_providers():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("llm.anthropic", {"api_key": ""}, category="llm")
    config.set("llm.gemini", {"api_key": ""}, category="llm")

    original_fetcher = ModelManager._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o"]
        return ["should-not-appear"]

    ModelManager._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = ModelManager(config()).get_available_models()
    finally:
        ModelManager._fetch_provider_models = original_fetcher

    assert models == {"openai": ["gpt-4o"]}


def test_get_available_models_does_not_fallback_on_fetch_error():
    config.set("llm.kimi", {"api_key": "bad-key"}, category="llm")

    original_fetcher = ModelManager._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        raise RuntimeError("HTTP 401 Unauthorized")

    ModelManager._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = ModelManager(config()).get_available_models()
    finally:
        ModelManager._fetch_provider_models = original_fetcher

    assert "kimi" not in models


def test_get_available_models_hides_provider_on_transient_fetch_error():
    config.set("llm.gemini", {"api_key": "sk-gemini"}, category="llm")

    original_fetcher = ModelManager._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        raise TimeoutError("The handshake operation timed out")

    ModelManager._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = ModelManager(config()).get_available_models()
    finally:
        ModelManager._fetch_provider_models = original_fetcher

    assert "gemini" not in models


def test_get_available_models_returns_saved_custom_model_without_probe():
    config.set(
        "llm.custom",
        {"api_key": "sk-custom", "base_url": "https://custom.example.com/v1", "model": "my-custom-model"},
        category="llm",
    )

    original_probe = ModelManager._probe_openai_compatible_chat_model

    def fake_probe(api_key: str, base_url: str, model: str):
        raise AssertionError("get_available_models should not probe custom chat availability")

    ModelManager._probe_openai_compatible_chat_model = staticmethod(fake_probe)
    try:
        models = ModelManager(config()).get_available_models()
    finally:
        ModelManager._probe_openai_compatible_chat_model = original_probe

    assert models["custom"] == ["my-custom-model"]


def test_validate_provider_config_returns_error_when_fetch_fails(monkeypatch):
    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        raise RuntimeError("HTTP 401 Unauthorized")

    monkeypatch.setattr(ModelManager, "_fetch_provider_models", staticmethod(fake_fetcher))

    message = ModelManager(config()).validate_provider_config("openai", "bad-key")

    assert message == "API key validation failed: HTTP 401 Unauthorized"


def test_validate_provider_config_allows_empty_api_key():
    assert ModelManager(config()).validate_provider_config("openai", "") is None


def test_validate_provider_config_requires_model_for_custom():
    assert ModelManager(config()).validate_provider_config("custom", "sk-custom", "https://custom.example.com/v1", "") == "Model is required."


def test_validate_provider_config_probes_custom_chat_model(monkeypatch):
    captured = {}

    def fake_probe(api_key: str, base_url: str, model: str):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["model"] = model

    monkeypatch.setattr(ModelManager, "_probe_openai_compatible_chat_model", staticmethod(fake_probe))

    assert ModelManager(config()).validate_provider_config("custom", "sk-custom", "https://custom.example.com/v1", "my-custom-model") is None
    assert captured == {
        "api_key": "sk-custom",
        "base_url": "https://custom.example.com/v1",
        "model": "my-custom-model",
    }


def test_get_active_model_id_returns_none_when_unset():
    assert ModelManager(config()).get_active_model_id() is None


def test_get_model_readiness_reports_no_runnable_model_when_unconfigured():
    readiness = ModelManager(config()).get_model_readiness()

    assert readiness == {
        "ready": False,
        "active_model": None,
        "issue": {"code": "no_runnable_model"},
    }


def test_get_model_readiness_reports_invalid_active_model_when_selection_missing():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")

    readiness = ModelManager(config()).get_model_readiness()

    assert readiness == {
        "ready": False,
        "active_model": None,
        "issue": {"code": "active_model_invalid"},
    }


def test_get_model_readiness_reports_missing_api_key_for_selected_provider():
    config.set("system.llm.active_model", "gemini:gemini-3-flash-preview", category="system")

    readiness = ModelManager(config()).get_model_readiness()

    assert readiness == {
        "ready": False,
        "active_model": "gemini:gemini-3-flash-preview",
        "issue": {
            "code": "missing_api_key",
            "provider": "gemini",
            "missing": ["api_key"],
        },
    }


def test_get_model_readiness_reports_ready_for_configured_active_model():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("system.llm.active_model", "openai:gpt-4o", category="system")

    readiness = ModelManager(config()).get_model_readiness()

    assert readiness == {
        "ready": True,
        "active_model": "openai:gpt-4o",
        "issue": None,
    }


def test_fetch_provider_models_routes_to_provider_specific_fetchers(monkeypatch):
    monkeypatch.setattr(ModelManager, "_fetch_anthropic_models", staticmethod(lambda api_key, base_url: ["claude-sonnet-4-5"]))
    monkeypatch.setattr(ModelManager, "_fetch_gemini_models", staticmethod(lambda api_key, base_url: ["gemini-3.1-pro-preview"]))
    monkeypatch.setattr(
        ModelManager,
        "_fetch_openai_compatible_models",
        staticmethod(
            lambda api_key, base_url: [
                "gpt-4o",
                "gpt-5.4-mini-2026-03-17",
                "gpt-5.4-nano-2026-03-17",
                "gpt-5.4-audio-preview-2026-03-17",
                "kimi-k2.5",
                "deepseek-v4-pro",
                "deepseek-v4-flash",
                "deepseek-r1-distill-qwen-32b",
                "deepseek-embedding",
                "moonshot-v1-8k-vision-preview",
                "doubao-seed-2-0-pro-260215",
                "doubao-seed-1-6-251015",
                "doubao-seed-2-0-code-preview-260215",
                "doubao-seedream-4-0-250828",
            ]
        ),
    )

    assert ModelManager._fetch_provider_models(
        "anthropic",
        "sk-a",
        "https://api.anthropic.com/v1",
        "anthropic",
    ) == ["claude-sonnet-4-5"]
    assert ModelManager._fetch_provider_models(
        "gemini",
        "sk-g",
        "https://generativelanguage.googleapis.com",
        "gemini",
    ) == ["gemini-3.1-pro-preview"]
    assert ModelManager._fetch_provider_models(
        "openai",
        "sk-o",
        "https://api.openai.com/v1",
        "openai_compatible",
    ) == ["gpt-5.4-mini-2026-03-17", "gpt-5.4-nano-2026-03-17"]
    assert ModelManager._fetch_provider_models(
        "deepseek",
        "sk-ds",
        "https://api.deepseek.com",
        "openai_compatible",
    ) == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert ModelManager._fetch_provider_models(
        "kimi",
        "sk-k",
        "https://api.moonshot.cn/v1",
        "openai_compatible",
    ) == ["kimi-k2.5"]

def test_fetch_provider_models_marks_missing_models_endpoint_as_unavailable(monkeypatch):
    def raise_not_found(api_key: str, base_url: str):
        raise HTTPError(base_url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(ModelManager, "_fetch_openai_compatible_models", staticmethod(raise_not_found))

    with pytest.raises(ModelListEndpointUnavailable):
        ModelManager._fetch_provider_models(
            "qwen",
            "sk-qwen",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai_compatible",
        )


def test_fetch_anthropic_models_falls_back_to_bearer_auth(monkeypatch):
    attempts = []

    def fake_http_get_json(url: str, headers=None, query=None):
        attempts.append(headers or {})
        if headers and headers.get("x-api-key"):
            raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=None)
        return {"data": [{"id": "claude-sonnet-4-6"}]}

    monkeypatch.setattr(ModelManager, "_http_get_json", staticmethod(fake_http_get_json))

    assert ModelManager._fetch_anthropic_models("sk-anthropic", "https://proxy.example.com/v1") == ["claude-sonnet-4-6"]
    assert attempts == [
        {
            "x-api-key": "sk-anthropic",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        {
            "Authorization": "Bearer sk-anthropic",
            "Content-Type": "application/json",
        },
    ]


def test_fetch_anthropic_models_marks_non_json_response_as_unavailable(monkeypatch):
    def fake_http_get_json(url: str, headers=None, query=None):
        raise JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(ModelManager, "_http_get_json", staticmethod(fake_http_get_json))

    with pytest.raises(ModelListEndpointUnavailable):
        ModelManager._fetch_anthropic_models("sk-anthropic", "https://proxy.example.com/v1")


def test_probe_openai_compatible_chat_model_uses_chat_completions_endpoint(monkeypatch):
    captured = {}

    def fake_http_post_json(url: str, payload=None, headers=None, query=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["query"] = query
        return {"id": "chatcmpl-test"}

    monkeypatch.setattr(ModelManager, "_http_post_json", staticmethod(fake_http_post_json))

    ModelManager._probe_openai_compatible_chat_model(
        "sk-custom",
        "https://custom.example.com/v1",
        "my-custom-model",
    )

    assert captured == {
        "url": "https://custom.example.com/v1/chat/completions",
        "payload": {
            "model": "my-custom-model",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        },
        "headers": {
            "Authorization": "Bearer sk-custom",
            "Content-Type": "application/json",
        },
        "query": None,
    }


def test_filter_chat_model_ids_excludes_non_chat_entries():
    filtered = ModelManager._filter_chat_model_ids([
        "gpt-4o",
        "text-embedding-3-large",
        "whisper-1",
        "claude-sonnet-4-5",
    ])

    assert filtered == ["gpt-4o", "claude-sonnet-4-5"]


def test_filter_gemini_models_keeps_only_llm_entries():
    filtered = ModelManager._filter_gemini_models([
        {
            "name": "models/gemini-2.0-flash-001",
            "baseModelId": "gemini-2.0-flash",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-2.0-flash-lite-001",
            "baseModelId": "",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-2.5-flash-native-audio-preview-09-2025",
            "baseModelId": "gemini-2.5-flash-native-audio-preview-09-2025",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-3.1-pro-preview",
            "baseModelId": "gemini-3.1-pro-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/veo-3.1-fast-generate-preview",
            "baseModelId": "veo-3.1-fast-generate-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/text-embedding-004",
            "baseModelId": "text-embedding-004",
            "supportedGenerationMethods": ["embedContent"],
        },
        {
            "name": "models/gemini-3.1-flash-live-preview",
            "baseModelId": "gemini-3.1-flash-live-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
    ])

    assert filtered == ["gemini-2.0-flash", "gemini-3.1-pro-preview"]


def test_filter_qwen_models_keeps_only_qwen_family_entries():
    filtered = ModelManager._filter_qwen_models([
        "MiniMax-M2.1",
        "deepseek-v3.1",
        "glm-4.7",
        "kimi-k2.5",
        "qwen3.6-plus-2026-04-02",
        "qwen3.6-plus",
        "qwen3.5-omni-plus-2026-03-15",
        "qwen3.5-omni-plus",
        "qwen3.5-omni-flash",
        "qwen3.5-flash",
        "qwen3.5-plus",
        "qwen3.5-397b-a17b",
        "qwen3-max",
        "qwen-plus",
        "qwen-max",
        "qwen-max-0107",
        "qwen-max-0428",
        "qwen-max-0919",
        "qwen-max-1201",
        "qwen-plus-2025-05-15",
        "qwen-max-2025-01-25",
        "qwen-vl-max",
        "qwen-omni-turbo",
        "qwen-omni-turbo-0119",
        "qwen3-32b",
        "qwen-coder-plus",
    ])

    assert filtered == [
        "qwen3.6-plus",
        "qwen3.5-plus",
        "qwen3.5-omni-plus",
        "qwen3.5-flash",
        "qwen3.5-omni-flash",
        "qwen3-max",
    ]


def test_filter_kimi_models_keeps_latest_three_supported_chat_models():
    filtered = ModelManager._filter_kimi_models([
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-thinking-turbo",
        "kimi-k2-0905-preview",
        "kimi-latest",
        "kimi-thinking-preview",
        "moonshot-v1-8k",
        "moonshot-v1-32k-vision-preview",
        "text-embedding-v1",
        "qwen-plus",
    ])

    assert filtered == [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2-thinking",
    ]


def test_filter_deepseek_models_prioritizes_current_chat_models():
    filtered = ModelManager._filter_deepseek_models([
        "deepseek-reasoner",
        "deepseek-v4-flash",
        "deepseek-embedding",
        "deepseek-v4-pro",
        "qwen-plus",
        "deepseek-chat",
        "deepseek-r1-distill-qwen-32b",
    ])

    assert filtered == [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-chat",
        "deepseek-reasoner",
    ]
