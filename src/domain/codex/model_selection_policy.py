"""Validate a model and reasoning effort together, preserving explicit choices."""

from src.core.codex_contract.host_contract import CodexHostCapabilities


def model_selection_error(
    capabilities: CodexHostCapabilities,
    model: str | None,
    reasoning_effort: str | None,
    *,
    inherited_model: str | None = None,
) -> str | None:
    if model is None and reasoning_effort is None:
        return None
    catalog = capabilities.model_catalog
    if catalog.state != "ready":
        return "主机模型能力尚未获取，请同步主机后重试。"
    selected = catalog.resolve(model or inherited_model)
    if selected is None:
        return "所选或继承模型不在主机当前可用模型中。"
    if reasoning_effort is not None and reasoning_effort not in selected.reasoning_efforts:
        return "当前模型不支持所选推理强度，请明确选择支持的组合。"
    return None
