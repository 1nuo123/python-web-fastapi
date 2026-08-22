"""Codex 工作区执行偏好的 capability 收敛测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

from src.application.codex.sync_agent_state_usecase import SyncCodexAgentStateUsecase
from src.application.codex.update_workspace_usecase import UpdateCodexWorkspaceUsecase
from src.core.codex_contract.agent_protocol_contract import CodexAgentWorkspaceSnapshot
from src.core.codex_contract.host_contract import (
    CodexApprovalPolicy,
    CodexHostCapabilities,
    CodexHostSnapshot,
    CodexSandboxMode,
)
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceExecutionPreferences,
    CodexWorkspaceExecutionPreferencesUpdate,
    CodexWorkspacePreferenceAdjustedField,
    CodexWorkspaceSnapshot,
)
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.domain.codex.workspace_execution_preference_policy import (
    build_codex_workspace_capabilities_revision,
    revalidate_codex_workspace_execution_preferences,
)

OWNER_SUBJECT_ID = "workspace-owner"
HOST_ID = uuid4()
WORKSPACE_ID = uuid4()
NOW = datetime(2026, 8, 19, 3, 30, tzinfo=UTC)
TOOL_SCOPES = frozenset(
    {
        AuthScopeCode.CODEX_FILES.value,
        AuthScopeCode.CODEX_TERMINAL.value,
        AuthScopeCode.CODEX_FULL_ACCESS.value,
    }
)


def _capabilities() -> CodexHostCapabilities:
    """构造拥有全部受支持策略的确定性主机能力。"""

    return CodexHostCapabilities(
        model_ids=("gpt-5.6", "gpt-5.5"),
        reasoning_efforts=("medium", "high"),
        sandbox_modes=(
            CodexSandboxMode.READ_ONLY,
            CodexSandboxMode.WORKSPACE_WRITE,
            CodexSandboxMode.DANGER_FULL_ACCESS,
        ),
        approval_policies=(
            CodexApprovalPolicy.UNTRUSTED,
            CodexApprovalPolicy.ON_REQUEST,
            CodexApprovalPolicy.NEVER,
        ),
    )


def _workspace(
    *,
    execution_preferences: CodexWorkspaceExecutionPreferences | None = None,
) -> CodexWorkspaceSnapshot:
    """构造不带敏感正文的工作区持久化快照。"""

    return CodexWorkspaceSnapshot(
        workspace_id=WORKSPACE_ID,
        host_id=HOST_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        agent_workspace_key="workspace-key",
        display_name="Workspace",
        is_pinned=False,
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
        version=3,
        execution_preferences=(
            execution_preferences
            if execution_preferences is not None
            else CodexWorkspaceExecutionPreferences()
        ),
    )


def _host() -> CodexHostSnapshot:
    """构造携带确定性 capability 的当前所有者主机。"""

    return CodexHostSnapshot(
        host_id=HOST_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        display_name="Host",
        platform="windows",
        status="online",
        capabilities=_capabilities(),
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def test_capabilities_revision_should_ignore_agent_advertisement_order() -> None:
    """同一能力集合改变上报顺序时不应触发错误的偏好回退。"""

    original = _capabilities()
    reordered = original.model_copy(
        update={
            "model_ids": tuple(reversed(original.model_ids)),
            "reasoning_efforts": tuple(reversed(original.reasoning_efforts)),
            "sandbox_modes": tuple(reversed(original.sandbox_modes)),
            "approval_policies": tuple(reversed(original.approval_policies)),
        }
    )

    assert build_codex_workspace_capabilities_revision(original) == (
        build_codex_workspace_capabilities_revision(reordered)
    )


def test_revalidation_should_reset_stale_model_and_reasoning_to_host_default() -> None:
    """失效模型和思考强度必须清空，让 App Server 使用当前默认值。"""

    preferences = CodexWorkspaceExecutionPreferences(
        model="retired-model",
        reasoning_effort="retired-effort",
        capabilities_revision=build_codex_workspace_capabilities_revision(_capabilities()),
    )

    effective, adjusted = revalidate_codex_workspace_execution_preferences(
        preferences,
        capabilities=_capabilities(),
        subject_scopes=TOOL_SCOPES,
    )

    assert effective.model is None
    assert effective.reasoning_effort is None
    assert adjusted == (
        CodexWorkspacePreferenceAdjustedField.MODEL,
        CodexWorkspacePreferenceAdjustedField.REASONING_EFFORT,
    )


def test_revalidation_should_downgrade_full_access_without_full_access_scope() -> None:
    """缺少 full_access scope 时不能保存 danger-full-access 沙箱。"""

    effective, adjusted = revalidate_codex_workspace_execution_preferences(
        CodexWorkspaceExecutionPreferencesUpdate(
            sandbox_mode=CodexSandboxMode.DANGER_FULL_ACCESS,
        ),
        capabilities=_capabilities(),
        subject_scopes=frozenset(
            {
                AuthScopeCode.CODEX_FILES.value,
                AuthScopeCode.CODEX_TERMINAL.value,
            }
        ),
    )

    assert effective.sandbox_mode is CodexSandboxMode.READ_ONLY
    assert CodexWorkspacePreferenceAdjustedField.SANDBOX_MODE in adjusted


def test_revalidation_should_exclude_unsupported_never_approval_policy() -> None:
    """产品不持久化 never，必须回退到最严格的官方支持策略。"""

    effective, adjusted = revalidate_codex_workspace_execution_preferences(
        CodexWorkspaceExecutionPreferencesUpdate(
            approval_policy=CodexApprovalPolicy.NEVER,
        ),
        capabilities=_capabilities(),
        subject_scopes=TOOL_SCOPES,
    )

    assert effective.approval_policy is CodexApprovalPolicy.UNTRUSTED
    assert CodexWorkspacePreferenceAdjustedField.APPROVAL_POLICY in adjusted


def test_workspace_preferences_revalidate_after_capability_change() -> None:
    """读取历史偏好只返回当前有效值，不应悄然修改工作区版本。"""

    control_port = Mock()
    unit_of_work = Mock()
    host_repository = Mock()
    workspace_repository = Mock()
    control_port.create_unit_of_work.return_value = unit_of_work
    unit_of_work.get_session.return_value = object()
    control_port.create_codex_host_repository.return_value = host_repository
    control_port.create_codex_workspace_repository.return_value = workspace_repository
    host_repository.get_by_id_and_owner.return_value = _host()
    workspace_repository.get_by_id_and_owner.return_value = _workspace(
        execution_preferences=CodexWorkspaceExecutionPreferences(
            model="retired-model",
            capabilities_revision="obsolete-capabilities",
        )
    )

    result = UpdateCodexWorkspaceUsecase(control_port=control_port).read_execution_preferences(
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        subject_scopes=TOOL_SCOPES,
    )

    assert result.effective_preferences.model is None
    assert set(result.adjusted_fields) == {
        CodexWorkspacePreferenceAdjustedField.MODEL,
        CodexWorkspacePreferenceAdjustedField.CAPABILITIES_REVISION,
    }
    workspace_repository.save.assert_not_called()
    unit_of_work.commit.assert_not_called()
    unit_of_work.dispose.assert_called_once()


def test_update_execution_preferences_should_store_server_revalidated_result() -> None:
    """PUT 只能提交服务端重算后的值，浏览器无权影响 capability 版本。"""

    control_port = Mock()
    unit_of_work = Mock()
    host_repository = Mock()
    workspace_repository = Mock()
    control_port.create_unit_of_work.return_value = unit_of_work
    unit_of_work.get_session.return_value = object()
    control_port.create_codex_host_repository.return_value = host_repository
    control_port.create_codex_workspace_repository.return_value = workspace_repository
    host_repository.get_by_id_and_owner.return_value = _host()
    workspace_repository.get_by_id_and_owner.return_value = _workspace()

    result = UpdateCodexWorkspaceUsecase(control_port=control_port).update_execution_preferences(
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        subject_scopes=TOOL_SCOPES,
        request=CodexWorkspaceExecutionPreferencesUpdate(
            model="retired-model",
            reasoning_effort="retired-effort",
            sandbox_mode=CodexSandboxMode.DANGER_FULL_ACCESS,
            approval_policy=CodexApprovalPolicy.NEVER,
        ),
    )

    saved = workspace_repository.save.call_args.args[0]
    assert saved.execution_preferences == result.effective_preferences
    assert saved.version == 4
    assert saved.execution_preferences.model is None
    assert saved.execution_preferences.reasoning_effort is None
    assert saved.execution_preferences.approval_policy is CodexApprovalPolicy.UNTRUSTED
    assert saved.execution_preferences.capabilities_revision == (
        build_codex_workspace_capabilities_revision(_capabilities())
    )
    unit_of_work.commit.assert_called_once()
    unit_of_work.dispose.assert_called_once()


def test_agent_workspace_snapshot_should_preserve_saved_execution_preferences() -> None:
    """Agent 工作区同步只更新控制元数据，不能覆盖用户保存的偏好。"""

    saved_preferences = CodexWorkspaceExecutionPreferences(
        model="gpt-5.6",
        reasoning_effort="high",
        sandbox_mode=CodexSandboxMode.READ_ONLY,
        approval_policy=CodexApprovalPolicy.ON_REQUEST,
        capabilities_revision="a" * 64,
    )
    existing = _workspace(execution_preferences=saved_preferences)

    updated = SyncCodexAgentStateUsecase(
        control_port=Mock(),
        max_workspaces_per_host=8,
    )._build_workspace_snapshot(
        host_id=HOST_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        captured_at=NOW,
        workspace=CodexAgentWorkspaceSnapshot(
            key="workspace-key",
            display_name="Renamed by Agent",
            allow_write=True,
        ),
        existing=existing,
    )

    assert updated.execution_preferences == saved_preferences
    assert updated.display_name == "Renamed by Agent"
    assert updated.version == existing.version + 1
