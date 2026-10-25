"""账号唯一活动 Remote 的切换契约。"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CodexActiveHostState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    active_host_id: UUID | None = None
    draining_host_id: UUID | None = None
    target_host_id: UUID | None = None
    version: int = Field(default=0, ge=0)
    activated_at: datetime | None = None
    drain_until: datetime | None = Field(
        default=None,
        description="停止续租后登记的执行许可最晚失效时间；空值表示尚未登记收尾期限。",
    )


class CodexActiveHostSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    host_id: UUID
    expected_version: int = Field(ge=0)
