"""Read the official model catalog without persisting user configuration."""

from __future__ import annotations

import asyncio

from pydantic import JsonValue

from src.core.codex_contract.model_catalog_contract import CodexModelCapability, CodexModelCatalog
from src.infrastructure.codex_agent.app_server_jsonrpc_client import AppServerJsonRpcClient


async def read_model_catalog(client: AppServerJsonRpcClient) -> CodexModelCatalog:
    """Bound pagination and total time; unavailable differs from an empty catalog."""

    models: dict[str, CodexModelCapability] = {}
    cursors: set[str] = set()
    cursor: str | None = None
    try:
        async with asyncio.timeout(10):
            for _ in range(16):
                params: dict[str, JsonValue] = {"limit": 100}
                if cursor is not None:
                    params["cursor"] = cursor
                result = await client.request("model/list", params, timeout_seconds=10)
                if not isinstance(result, dict):
                    raise ValueError("Invalid model catalog")
                raw_models = result.get("data")
                if not isinstance(raw_models, list):
                    raise ValueError("Invalid model catalog")
                for raw in raw_models:
                    if not isinstance(raw, dict) or raw.get("hidden") is True:
                        continue
                    model = raw.get("model")
                    efforts = raw.get("supportedReasoningEfforts")
                    if not isinstance(model, str) or not isinstance(efforts, list):
                        raise ValueError("Incomplete model capability")
                    model_efforts = tuple(
                        option["reasoningEffort"]
                        for option in efforts
                        if isinstance(option, dict) and isinstance(option.get("reasoningEffort"), str)
                    )
                    models[model] = CodexModelCapability.model_validate({
                        "model": model,
                        "display_name": raw.get("displayName") or model,
                        "reasoning_efforts": model_efforts,
                        "default_reasoning_effort": raw.get("defaultReasoningEffort"),
                        "is_default": raw.get("isDefault", False),
                    })
                    if len(models) > 512:
                        raise ValueError("Model catalog exceeds bound")
                next_cursor = result.get("nextCursor")
                if next_cursor is None:
                    return CodexModelCatalog(state="ready", models=tuple(models.values()))
                if not isinstance(next_cursor, str) or next_cursor in cursors:
                    raise ValueError("Invalid model cursor")
                cursor = next_cursor
                cursors.add(cursor)
    except (TimeoutError, RuntimeError, ValueError, ConnectionError):
        pass
    return CodexModelCatalog(state="unavailable")
