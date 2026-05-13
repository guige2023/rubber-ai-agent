from __future__ import annotations

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps, get_model_pricing_service
from app.core.toolkits.base import Toolkit


class PricingToolkit(Toolkit):
    """Inspect the in-memory model pricing catalog."""

    @staticmethod
    def get_tools():
        return [PricingToolkit.get_model_pricing]

    @staticmethod
    async def get_model_pricing(
        ctx: RunContext[AgentDeps],
        model_id: str | None = None,
    ) -> dict[str, object]:
        """Return cached model pricing in USD per million tokens.

        Args:
            model_id: Optional Ferryman model id such as
                "gemini:gemini-3-flash-preview" or "qwen:qwen3.6-plus".
                If omitted, returns all cached model prices.
        """
        pricing_service = get_model_pricing_service(ctx.deps)
        if pricing_service is None:
            raise ModelRetry("Model pricing service is not available.")

        catalog = pricing_service.catalog
        if not catalog.models:
            return {
                "status": catalog.status,
                "refreshed_at": catalog.refreshed_at,
                "models": {},
                "message": "Model pricing cache is empty. It may still be refreshing.",
                "refresh_errors": catalog.refresh_errors,
            }

        if model_id:
            normalized_model_id = model_id.strip()
            price = catalog.models.get(normalized_model_id)
            if price is None:
                return {
                    "status": catalog.status,
                    "refreshed_at": catalog.refreshed_at,
                    "model_id": normalized_model_id,
                    "found": False,
                    "available_models": sorted(catalog.models),
                    "refresh_errors": catalog.refresh_errors,
                }
            return {
                "status": catalog.status,
                "refreshed_at": catalog.refreshed_at,
                "model_id": normalized_model_id,
                "found": True,
                "price": price.snapshot(),
                "fx": _fx_snapshot(catalog),
            }

        return {
            "status": catalog.status,
            "refreshed_at": catalog.refreshed_at,
            "expires_at": catalog.expires_at,
            "currency": "USD",
            "unit": "per_million_tokens",
            "models": {
                model_key: price.snapshot()
                for model_key, price in sorted(catalog.models.items())
            },
            "fx": _fx_snapshot(catalog),
            "refresh_errors": catalog.refresh_errors,
        }


def _fx_snapshot(catalog) -> dict[str, object]:
    return {
        key: {
            "rate": rate.rate,
            "date": rate.date,
            "source": rate.source,
            "stale": rate.stale,
        }
        for key, rate in catalog.fx.items()
    }
