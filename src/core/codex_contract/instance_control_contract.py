"""跨 API 实例的 Codex 控制信号契约。"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexDispatchSignalDetail(BaseModel):
    """不含命令明文的 dispatch 引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["dispatch"] = "dispatch"
    command_id: UUID
    host_id: UUID
    route_fencing_token: int = Field(gt=0)


class CodexRevokeSignalDetail(BaseModel):
    """跨实例撤销 host socket。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["revoke"] = "revoke"
    host_id: UUID
    revocation_generation: int = Field(gt=0)


CodexInstanceControlDetail = Annotated[
    CodexDispatchSignalDetail | CodexRevokeSignalDetail,
    Field(discriminator="kind"),
]


class CodexInstanceControlSignal(BaseModel):
    """绑定目标实例的控制信号。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    target_instance_id: UUID
    detail: CodexInstanceControlDetail
