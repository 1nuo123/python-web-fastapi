"""Codex 产品命令与 App Server 方法的一一映射契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerMethodName,
)


class CodexProductCommandCode(StrEnum):
    """控制面允许投递的封闭产品命令集合。"""

    THREAD_LIST = "thread.list"
    THREAD_READ = "thread.read"
    THREAD_START = "thread.start"
    THREAD_RESUME = "thread.resume"
    THREAD_NAME_SET = "thread.name_set"
    THREAD_ARCHIVE = "thread.archive"
    THREAD_UNARCHIVE = "thread.unarchive"
    THREAD_COMPACT = "thread.compact"
    TURN_START = "turn.start"
    TURN_STEER = "turn.steer"
    TURN_INTERRUPT = "turn.interrupt"
    APPROVAL_DECISION = "approval.decision"


class CodexProductOwnershipScope(StrEnum):
    """命令执行前必须验证的所有权范围。"""

    OWNER = "owner"
    HOST = "host"
    WORKSPACE = "workspace"
    THREAD = "thread"
    APPROVAL = "approval"


class CodexProductCommandPolicy(BaseModel):
    """产品命令的官方方法、能力和所有权要求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: CodexProductCommandCode
    app_server_method: AppServerMethodName | None
    required_capability: AppServerCapabilityCode
    ownership_scope: CodexProductOwnershipScope
    mutation: bool


class CodexProductCommandCatalog:
    """提供唯一的产品命令映射目录。"""

    def build(self) -> tuple[CodexProductCommandPolicy, ...]:
        """返回产品命令到已审核 App Server 方法的完整映射。"""

        return (
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_LIST,
                app_server_method=AppServerMethodName.THREAD_LIST,
                required_capability=AppServerCapabilityCode.THREAD_LIST,
                ownership_scope=CodexProductOwnershipScope.WORKSPACE,
                mutation=False,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_READ,
                app_server_method=AppServerMethodName.THREAD_READ,
                required_capability=AppServerCapabilityCode.THREAD_READ,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=False,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_START,
                app_server_method=AppServerMethodName.THREAD_START,
                required_capability=AppServerCapabilityCode.THREAD_START,
                ownership_scope=CodexProductOwnershipScope.WORKSPACE,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_RESUME,
                app_server_method=AppServerMethodName.THREAD_RESUME,
                required_capability=AppServerCapabilityCode.THREAD_RESUME,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_NAME_SET,
                app_server_method=AppServerMethodName.THREAD_NAME_SET,
                required_capability=AppServerCapabilityCode.THREAD_NAME_SET,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_ARCHIVE,
                app_server_method=AppServerMethodName.THREAD_ARCHIVE,
                required_capability=AppServerCapabilityCode.THREAD_ARCHIVE,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_UNARCHIVE,
                app_server_method=AppServerMethodName.THREAD_UNARCHIVE,
                required_capability=AppServerCapabilityCode.THREAD_UNARCHIVE,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.THREAD_COMPACT,
                app_server_method=AppServerMethodName.THREAD_COMPACT_START,
                required_capability=AppServerCapabilityCode.THREAD_COMPACT,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.TURN_START,
                app_server_method=AppServerMethodName.TURN_START,
                required_capability=AppServerCapabilityCode.TURN_START,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.TURN_STEER,
                app_server_method=AppServerMethodName.TURN_STEER,
                required_capability=AppServerCapabilityCode.TURN_STEER,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.TURN_INTERRUPT,
                app_server_method=AppServerMethodName.TURN_INTERRUPT,
                required_capability=AppServerCapabilityCode.TURN_INTERRUPT,
                ownership_scope=CodexProductOwnershipScope.THREAD,
                mutation=True,
            ),
            CodexProductCommandPolicy(
                command=CodexProductCommandCode.APPROVAL_DECISION,
                app_server_method=None,
                required_capability=AppServerCapabilityCode.APPROVAL_COMMAND,
                ownership_scope=CodexProductOwnershipScope.APPROVAL,
                mutation=True,
            ),
        )

    def read(self, command: CodexProductCommandCode) -> CodexProductCommandPolicy:
        """按产品命令读取唯一策略。"""

        for policy in self.build():
            if policy.command == command:
                return policy
        raise ValueError("Codex产品命令目录缺少映射。")
