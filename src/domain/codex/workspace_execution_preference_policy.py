"""Codex 工作区执行偏好 capability 与授权收敛规则。"""

from __future__ import annotations

from hashlib import sha256
from json import dumps

from src.core.codex_contract.host_contract import (
    CodexApprovalPolicy,
    CodexHostCapabilities,
    CodexSandboxMode,
)
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceExecutionPreferences,
    CodexWorkspaceExecutionPreferencesUpdate,
    CodexWorkspacePreferenceAdjustedField,
)
from src.domain.auth.auth_scope_code import AuthScopeCode

SANDBOX_RESTRICTION_ORDER: tuple[CodexSandboxMode, ...] = (
    CodexSandboxMode.READ_ONLY,
    CodexSandboxMode.WORKSPACE_WRITE,
    CodexSandboxMode.DANGER_FULL_ACCESS,
)
APPROVAL_RESTRICTION_ORDER: tuple[CodexApprovalPolicy, ...] = (
    CodexApprovalPolicy.UNTRUSTED,
    CodexApprovalPolicy.ON_REQUEST,
)


def build_codex_workspace_capabilities_revision(
    capabilities: CodexHostCapabilities,
) -> str:
    """构造可重现的 capability 摘要；只使用封闭枚举和能力标识，不含正文。"""

    canonical = dumps(
        {
            # Agent 上报顺序没有语义，排序后才能避免无意义的 capability 版本抖动。
            "approval_policies": sorted(item.value for item in capabilities.approval_policies),
            "model_ids": sorted(capabilities.model_ids),
            "reasoning_efforts": sorted(capabilities.reasoning_efforts),
            "model_catalog": capabilities.model_catalog.model_dump(mode="json"),
            "sandbox_modes": sorted(item.value for item in capabilities.sandbox_modes),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def revalidate_codex_workspace_execution_preferences(
    preferences: CodexWorkspaceExecutionPreferences | CodexWorkspaceExecutionPreferencesUpdate,
    *,
    capabilities: CodexHostCapabilities,
    subject_scopes: frozenset[str],
) -> tuple[
    CodexWorkspaceExecutionPreferences,
    tuple[CodexWorkspacePreferenceAdjustedField, ...],
]:
    """按当前 capability 和请求主体权限收敛工作区偏好。

    保留用户明确选择的模型和推理强度，由命令入口校验支持情况。
    安全策略收敛到可用集合，不能保留过期能力的较宽松配置。
    """

    adjusted_fields: list[CodexWorkspacePreferenceAdjustedField] = []
    capability_revision = build_codex_workspace_capabilities_revision(capabilities)
    model = preferences.model
    reasoning_effort = preferences.reasoning_effort

    sandbox_mode = _resolve_sandbox_mode(
        requested=preferences.sandbox_mode,
        capabilities=capabilities,
        subject_scopes=subject_scopes,
    )
    if sandbox_mode is not preferences.sandbox_mode:
        adjusted_fields.append(CodexWorkspacePreferenceAdjustedField.SANDBOX_MODE)

    approval_policy = _resolve_approval_policy(
        requested=preferences.approval_policy,
        capabilities=capabilities,
    )
    if approval_policy is not preferences.approval_policy:
        adjusted_fields.append(CodexWorkspacePreferenceAdjustedField.APPROVAL_POLICY)

    previous_revision = getattr(preferences, "capabilities_revision", None)
    if previous_revision != capability_revision:
        adjusted_fields.append(CodexWorkspacePreferenceAdjustedField.CAPABILITIES_REVISION)

    return (
        CodexWorkspaceExecutionPreferences(
            model=model,
            reasoning_effort=reasoning_effort,
            sandbox_mode=sandbox_mode,
            approval_policy=approval_policy,
            capabilities_revision=capability_revision,
        ),
        tuple(adjusted_fields),
    )


def _resolve_sandbox_mode(
    *,
    requested: CodexSandboxMode,
    capabilities: CodexHostCapabilities,
    subject_scopes: frozenset[str],
) -> CodexSandboxMode:
    """选择 capability 与 scope 共同允许的最严格沙箱，拒绝陈旧宽权限。"""

    supported = set(capabilities.sandbox_modes)
    has_tool_scopes = {
        AuthScopeCode.CODEX_FILES.value,
        AuthScopeCode.CODEX_TERMINAL.value,
    }.issubset(subject_scopes)
    allowed = [
        mode
        for mode in SANDBOX_RESTRICTION_ORDER
        if mode in supported
        and (mode is CodexSandboxMode.READ_ONLY or has_tool_scopes)
        and (
            mode is not CodexSandboxMode.DANGER_FULL_ACCESS
            or AuthScopeCode.CODEX_FULL_ACCESS.value in subject_scopes
        )
    ]
    if requested in allowed:
        return requested
    return allowed[0] if allowed else CodexSandboxMode.READ_ONLY


def _resolve_approval_policy(
    *,
    requested: CodexApprovalPolicy,
    capabilities: CodexHostCapabilities,
) -> CodexApprovalPolicy:
    """只保留产品已支持的审批策略，并优先回退到最严格策略。"""

    allowed = [
        policy for policy in APPROVAL_RESTRICTION_ORDER if policy in capabilities.approval_policies
    ]
    if requested in allowed:
        return requested
    return allowed[0] if allowed else CodexApprovalPolicy.UNTRUSTED
