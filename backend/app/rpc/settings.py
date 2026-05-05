from __future__ import annotations

import asyncio

from jsonrpcserver import Success, method

from app.core.config import get_settings


@method
async def get_llm_configs(context):
    """Return consolidated API configurations for supported providers."""
    settings = get_settings()
    providers = context.runtime.model_manager.get_llm_provider_catalog()

    results = []
    for provider, metadata in providers.items():
        raw_config = settings.get(f"llm.{provider}", {})
        stored_config = raw_config if isinstance(raw_config, dict) else {}

        results.append({
            "provider": provider,
            "api_key": str(stored_config.get("api_key", "")),
            "base_url": str(stored_config.get("base_url", "")),
            "model": str(stored_config.get("model", "")),
            "metadata": {
                "label": metadata.get("label", provider.capitalize()),
                "placeholder_base_url": metadata.get("placeholder_base_url", ""),
                "placeholder_model": metadata.get("placeholder_model", ""),
                "supports_model": bool(metadata.get("supports_model", False)),
            }
        })

    return Success(results)


@method
async def set_llm_config(
    context,
    provider: str,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
):
    """Update the consolidated config object for a provider."""
    key = f"llm.{provider}"
    settings = get_settings()
    raw_config = settings.get(key, {})
    current_config = raw_config if isinstance(raw_config, dict) else {}

    if api_key is not None:
        current_config["api_key"] = api_key
    if base_url is not None:
        current_config["base_url"] = base_url.strip() if base_url.strip() else ""
    if model is not None and provider == "custom":
        current_config["model"] = model.strip() if model.strip() else ""

    validation_error = await asyncio.to_thread(
        context.runtime.model_manager.validate_provider_config,
        provider,
        str(current_config.get("api_key", "")),
        str(current_config.get("base_url", "")),
        str(current_config.get("model", "")),
    )
    if validation_error:
        return Success({"status": "error", "message": validation_error})

    settings.set(key, current_config, category="llm")
    return Success({"status": "success"})


@method
async def get_active_model(context):
    """Return the currently active model identifier."""
    return Success(context.runtime.model_manager.get_active_model_id())


@method
async def get_model_readiness(context):
    """Return whether Ferryman has a usable active model for chat."""
    return Success(context.runtime.model_manager.get_model_readiness())


@method
async def set_active_model(context, model: str):
    """Update the active model globally."""
    context.runtime.model_manager.set_active_model(model)
    return Success({"status": "success"})


@method
async def get_available_models(context):
    """Return the mapped candidate models for the UI select."""
    return Success(await asyncio.to_thread(context.runtime.model_manager.get_available_models))
