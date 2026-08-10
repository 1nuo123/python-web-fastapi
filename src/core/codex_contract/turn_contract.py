"""Codex turn 命令契约。"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode


class CodexExecutionOptions(BaseModel):
    """由 Agent capability 限定的执行选项。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str | None = Field(default=None, min_length=1, max_length=128)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=64)
    sandbox_mode: CodexSandboxMode = CodexSandboxMode.WORKSPACE_WRITE
    approval_policy: CodexApprovalPolicy = CodexApprovalPolicy.UNTRUSTED


class CodexThreadCreateRequest(BaseModel):
    """创建本地持久 thread 的产品请求。"""

    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    execution: CodexExecutionOptions = Field(default_factory=CodexExecutionOptions)


class CodexTurnStartRequest(BaseModel):
    """向已有 thread 发起文本 turn 的产品请求。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=200_000)
    execution: CodexExecutionOptions = Field(default_factory=CodexExecutionOptions)


class CodexOperationAccepted(BaseModel):
    """HTTP 202 返回的稳定 operation 身份。"""

    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    command_id: UUID
    status: str
    replayed: bool = False


class CodexTurnCommand(BaseModel):
    """控制面受理后投递给 Agent 的稳定命令身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID
    command_id: UUID
    request_digest: str = Field(min_length=64, max_length=64)
    host_id: UUID
    workspace_id: UUID
    upstream_thread_id: str | None = Field(default=None, max_length=256)
    operation_type: str = Field(min_length=1, max_length=64)
