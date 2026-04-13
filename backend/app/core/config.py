import json
import logging
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Immutable system-level configurations and path defaults.
    Values are loaded from environment variables or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

    # Base directory for all Ferryman persistence
    root_dir: Path = Field(default=Path.home() / ".ferryman", validation_alias="FERRYMAN_ROOT_DIR")
    port: int = 8000
    log_level: str = Field(
        default="DEBUG",
        validation_alias=AliasChoices("FERRYMAN_LOG_LEVEL", "LOG_LEVEL"),
    )

    @property
    def user_dir(self) -> Path:
        # This is the "Identity" folder that users can export/migrate
        return self.root_dir / "user"

    @property
    def db_path(self) -> Path:
        # DB must be inside user_dir to migrate sessions and settings
        return self.user_dir / "ferryman.db"

    @property
    def log_dir(self) -> Path:
        return self.user_dir / "logs"

    @property
    def browser_dir(self) -> Path:
        return self.user_dir / "browser"

    @property
    def user_skills_dir(self) -> Path:
        return self.user_dir / "skills"

    @property
    def bundled_skills_dir(self) -> Path:
        """Return the built-in skills directory for the current runtime."""
        env_override = os.environ.get("FERRYMAN_BUNDLED_SKILLS_DIR")
        if env_override:
            return Path(env_override).expanduser()

        repo_skills_dir = Path(__file__).resolve().parents[3] / "skills"
        if repo_skills_dir.exists():
            return repo_skills_dir

        meipass_dir = getattr(sys, "_MEIPASS", None)
        if meipass_dir:
            return Path(meipass_dir) / "skills"

        executable_path = Path(sys.executable).resolve()
        app_bundle_resources_dir = executable_path.parents[1] / "Resources" / "skills"
        if app_bundle_resources_dir.exists():
            return app_bundle_resources_dir

        return repo_skills_dir

    @property
    def skills_dir(self) -> tuple[Path, Path]:
        # Returns a tuple of (bundled, user) skill directories
        return (
            self.bundled_skills_dir,
            self.user_skills_dir,
        )

    # --- Runtime Registry Methods (Database Persistent) ---
    # Note: Using local imports inside methods to avoid circular dependencies with db.py

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """Retrieves a configuration value from the database."""
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.key == key)
            record = session.exec(statement).first()
            return record.value if record else default

    @staticmethod
    def set(key: str, value: Any, category: str = "general", metadata: Optional[Dict] = None) -> Any:
        """Sets a configuration value in the database."""
        from datetime import datetime, timezone
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.key == key)
            record = session.exec(statement).first()

            if record:
                record.value = value
                record.category = category
                if metadata:
                    record.metadata_.update(metadata)
                record.updated_at = datetime.now(timezone.utc)
            else:
                record = AppConfig(
                    key=key,
                    value=value,
                    category=category,
                    metadata_=metadata or {},
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(record)

            session.commit()
            session.refresh(record)
            return record

    def get_provider_llm_config(self, provider: str) -> Dict[str, Any]:
        """Consolidated fetcher for provider-specific LLM settings."""
        # Database stores structure like {"api_key": "...", "base_url": "..."}
        raw = self.get(f"llm.{provider}", {})

        # Explicitly filter for PydanticAI Provider supported keys
        valid_keys = {"api_key", "base_url"}

        config = {}
        for k in valid_keys:
            val = raw.get(k)
            # Only pass values that are non-empty strings (after stripping)
            # This allows PydanticAI to use defaults if the field is empty in Ferryman
            if val and str(val).strip():
                config[k] = val

        return config

    @staticmethod
    def get_llm_provider_catalog() -> Dict[str, Dict[str, Any]]:
        """Returns the provider metadata used by the settings UI and model registry."""
        return {
            "gemini": {
                "label": "Gemini",
                "placeholder_base_url": "https://generativelanguage.googleapis.com",
                "list_mode": "gemini",
                "models": [
                    "gemini-3.1-pro-preview",
                    "gemini-3.1-flash-lite-preview",
                    "gemini-3-flash-preview",
                ],
            },
            "openai": {
                "label": "OpenAI",
                "placeholder_base_url": "https://api.openai.com/v1",
                "list_mode": "openai_compatible",
                "models": [
                    "gpt-5.4-pro",
                    "gpt-5.4-thinking",
                    "gpt-5.3-instant",
                    "gpt-5.3-codex",
                    "gpt-4o",
                    "gpt-4o-mini",
                ],
            },
            "anthropic": {
                "label": "Claude",
                "placeholder_base_url": "https://api.anthropic.com/v1",
                "list_mode": "anthropic",
                "models": [
                    "claude-opus-4.6",
                    "claude-sonnet-4.6",
                    "claude-haiku-4.5",
                    "claude-3-5-sonnet-latest",
                ],
            },
            "qwen": {
                "label": "Qwen",
                "placeholder_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "list_mode": "openai_compatible",
                "models": [
                    "qwen-max",
                    "qwen-plus",
                    "qwen3.5-plus",
                    "qwen3.5-omni-plus",
                ],
            },
            "kimi": {
                "label": "Kimi",
                "placeholder_base_url": "https://api.moonshot.ai/v1",
                "list_mode": "openai_compatible",
                "models": [
                    "kimi-k2.5",
                    "kimi-k2-thinking",
                    "kimi-k2-thinking-turbo",
                    "kimi-k2-0905-preview",
                    "kimi-k2-turbo-preview",
                    "moonshot-v1-128k",
                ],
            },
            "custom": {
                "label": "Custom",
                "placeholder_base_url": "https://api.example.com/v1",
                "placeholder_model": "your-model-name",
                "supports_model": True,
                "list_mode": "openai_compatible",
                "models": [],
            },
        }

    def get_active_model_id(self) -> str:
        """Returns the globally active model identifier."""
        return self.get("system.llm.active_model", "gemini:gemini-3-flash-preview")

    @staticmethod
    def list_by_category(category: str) -> List[Any]:
        """Lists all configurations in a given category."""
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.category == category)
            return list(session.exec(statement).all())

    @staticmethod
    def get_available_models() -> Dict[str, List[str]]:
        """Returns a registry of available models for configured providers."""
        catalog = Settings.get_llm_provider_catalog()
        available_models: Dict[str, List[str]] = {}

        for provider, definition in catalog.items():
            stored_config = Settings.get(f"llm.{provider}", {})
            api_key = str(stored_config.get("api_key", "")).strip()
            base_url = str(stored_config.get("base_url", "")).strip() or definition.get("placeholder_base_url", "")
            configured_model = str(stored_config.get("model", "")).strip()

            provider_models: List[str] = []

            if provider == "custom":
                if api_key and base_url:
                    provider_models = Settings._fetch_provider_models(
                        provider=provider,
                        api_key=api_key,
                        base_url=base_url,
                        list_mode=definition.get("list_mode", "openai_compatible"),
                    )
                if configured_model:
                    provider_models = [*provider_models, configured_model]
            elif api_key:
                provider_models = Settings._fetch_provider_models(
                    provider=provider,
                    api_key=api_key,
                    base_url=base_url,
                    list_mode=definition.get("list_mode", "openai_compatible"),
                )
                if not provider_models:
                    provider_models = list(definition.get("models", []))

            deduped_models = list(dict.fromkeys(model for model in provider_models if model))
            if deduped_models:
                available_models[provider] = deduped_models

        active_model_id = Settings.get("system.llm.active_model", "gemini:gemini-3-flash-preview")
        if ":" in active_model_id:
            provider, model_name = active_model_id.split(":", 1)
            model_name = model_name.strip()
            if provider in available_models and model_name and model_name not in available_models[provider]:
                available_models[provider].append(model_name)

        return available_models

    @staticmethod
    def _fetch_provider_models(provider: str, api_key: str, base_url: str, list_mode: str) -> List[str]:
        try:
            if list_mode == "anthropic":
                return Settings._fetch_anthropic_models(api_key=api_key, base_url=base_url)
            if list_mode == "gemini":
                return Settings._fetch_gemini_models(api_key=api_key, base_url=base_url)
            model_ids = Settings._fetch_openai_compatible_models(api_key=api_key, base_url=base_url)
            if provider == "qwen":
                return Settings._filter_qwen_models(model_ids)
            if provider == "kimi":
                return Settings._filter_kimi_models(model_ids)
            return model_ids
        except Exception as exc:
            logger.warning(f"Failed to fetch models for provider {provider}: {exc}")
            return []

    @staticmethod
    def _http_get_json(url: str, headers: Optional[Dict[str, str]] = None, query: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if query:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(query)}"

        request = Request(url, headers=headers or {}, method="GET")
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _build_openai_compatible_models_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        return normalized if normalized.endswith("/models") else f"{normalized}/models"

    @staticmethod
    def _build_gemini_models_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/models"):
            return normalized
        if normalized.endswith("/v1beta"):
            return f"{normalized}/models"
        return f"{normalized}/v1beta/models"

    @staticmethod
    def _filter_chat_model_ids(model_ids: List[str]) -> List[str]:
        excluded_keywords = (
            "embedding",
            "embed",
            "moderation",
            "image",
            "vision-preview",
            "whisper",
            "transcribe",
            "tts",
            "speech",
            "rerank",
        )
        filtered = [
            model_id
            for model_id in model_ids
            if model_id and not any(keyword in model_id.lower() for keyword in excluded_keywords)
        ]
        return sorted(dict.fromkeys(filtered))

    @staticmethod
    def _has_trailing_build_or_date_variant(model_id: str) -> bool:
        normalized = model_id.lower().strip()
        return bool(
            re.search(r"-\d{3,4}$", normalized)
            or re.search(r"-\d{4}-\d{2}-\d{2}$", normalized)
        )

    @staticmethod
    def _filter_gemini_models(models: List[Dict[str, Any]]) -> List[str]:
        allowed_models: List[str] = []
        excluded_keywords = (
            "audio",
            "live",
            "computer-use",
            "image",
        )

        for item in models:
            if not isinstance(item, dict):
                continue

            supported_methods = {
                str(method).strip()
                for method in item.get("supportedGenerationMethods", [])
                if str(method).strip()
            }
            if "generateContent" not in supported_methods:
                continue

            model_id = str(item.get("baseModelId", "")).strip()
            if not model_id:
                model_id = str(item.get("name", "")).strip()
                if model_id.startswith("models/"):
                    model_id = model_id.split("/", 1)[1]

            normalized_model_id = model_id.lower()
            if not normalized_model_id.startswith("gemini-"):
                continue
            if any(keyword in normalized_model_id for keyword in excluded_keywords):
                continue
            if Settings._has_trailing_build_or_date_variant(normalized_model_id):
                continue

            allowed_models.append(model_id)

        return sorted(dict.fromkeys(allowed_models))

    @staticmethod
    def _filter_qwen_models(model_ids: List[str]) -> List[str]:
        allowed_prefixes = (
            "qwen-max",
            "qwen-plus",
            "qwen-omni",
        )
        allowed_exact = {
            "qwen3.5-plus",
        }
        excluded_keywords = (
            "embedding",
            "embed",
            "audio",
            "image",
            "vision",
            "vl",
            "tts",
            "asr",
            "rerank",
        )

        filtered = []
        for model_id in model_ids:
            normalized = model_id.lower()
            if normalized in allowed_exact:
                filtered.append(model_id)
                continue
            if not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            if Settings._has_trailing_build_or_date_variant(normalized):
                continue
            filtered.append(model_id)

        return sorted(dict.fromkeys(filtered))

    @staticmethod
    def _filter_kimi_models(model_ids: List[str]) -> List[str]:
        allowed_prefixes = (
            "kimi-k2",
            "moonshot-v1",
        )
        deprecated_models = {
            "kimi-latest",
            "kimi-thinking-preview",
        }
        excluded_keywords = (
            "embedding",
            "embed",
            "vision",
            "image",
            "audio",
            "video",
            "tts",
            "asr",
            "rerank",
        )

        filtered = []
        for model_id in model_ids:
            normalized = model_id.lower().strip()
            if not normalized or normalized in deprecated_models:
                continue
            if not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            filtered.append(model_id)

        return sorted(dict.fromkeys(filtered))

    @staticmethod
    def _fetch_openai_compatible_models(api_key: str, base_url: str) -> List[str]:
        payload = Settings._http_get_json(
            Settings._build_openai_compatible_models_url(base_url),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        model_ids = [
            item.get("id", "").strip()
            for item in payload.get("data", [])
            if isinstance(item, dict)
        ]
        return Settings._filter_chat_model_ids(model_ids)

    @staticmethod
    def _fetch_anthropic_models(api_key: str, base_url: str) -> List[str]:
        payload = Settings._http_get_json(
            Settings._build_openai_compatible_models_url(base_url),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        model_ids = [
            item.get("id", "").strip()
            for item in payload.get("data", [])
            if isinstance(item, dict)
        ]
        return Settings._filter_chat_model_ids(model_ids)

    @staticmethod
    def _fetch_gemini_models(api_key: str, base_url: str) -> List[str]:
        payload = Settings._http_get_json(
            Settings._build_gemini_models_url(base_url),
            query={"key": api_key},
        )
        return Settings._filter_gemini_models(payload.get("models", []))


@lru_cache()
def get_settings() -> Settings:
    """获取应用配置实例（单例模式）"""
    return Settings()
