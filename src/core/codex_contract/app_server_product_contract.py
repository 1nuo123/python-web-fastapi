"""App Server 官方 notification 到产品边界的窄强类型契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.core.codex_contract.thread_contract import CodexPlanStepStatus

APP_SERVER_PRODUCT_NOTIFICATION_KIND: Final = "app_server_product_notification"
APP_SERVER_PRODUCT_NOTIFICATION_SCHEMA_VERSION: Final = "1.0"
APP_SERVER_PRODUCT_MAX_TEXT_CHARS: Final = 1_048_576
APP_SERVER_PRODUCT_MAX_DELTA_CHARS: Final = 65_536


class AppServerProtocolWarningReason(StrEnum):
    """未知或损坏官方消息的稳定原因码。"""

    UNKNOWN_NOTIFICATION = "unknown_notification"
    MALFORMED_PAYLOAD = "malformed_payload"
    UNKNOWN_ENUM = "unknown_enum"
    PAYLOAD_TOO_LARGE = "payload_too_large"


class AppServerProductItemBase(BaseModel):
    """App Server 产品时间线条目的公共定位字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1, max_length=256)


class AppServerUserMessageItem(AppServerProductItemBase):
    """已脱敏的用户文本消息。"""

    kind: Literal["user_message"] = "user_message"
    text: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)


class AppServerAgentMessageItem(AppServerProductItemBase):
    """Agent 最终或流式文本消息。"""

    kind: Literal["agent_message"] = "agent_message"
    text: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)


class AppServerNoticeItem(AppServerProductItemBase):
    """推理摘要或暂不单独展示的官方条目。"""

    kind: Literal["notice"] = "notice"
    label: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)


class AppServerContextCompactionItem(AppServerProductItemBase):
    """上下文压缩生命周期条目。"""

    kind: Literal["context_compaction"] = "context_compaction"


class AppServerPlanStep(BaseModel):
    """可直接渲染的计划步骤。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step: str = Field(min_length=1, max_length=4_096)
    status: CodexPlanStepStatus


class AppServerPlanItem(AppServerProductItemBase):
    """结构化计划条目。"""

    kind: Literal["plan"] = "plan"
    explanation: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    steps: tuple[AppServerPlanStep, ...] = ()


class AppServerCommandItem(AppServerProductItemBase):
    """命令及其有界输出。"""

    kind: Literal["command"] = "command"
    command: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    output: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    exit_code: int | None = None


class AppServerDiffItem(AppServerProductItemBase):
    """等待应用层结构化解析的有界 unified diff。"""

    kind: Literal["diff"] = "diff"
    unified_diff: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)


AppServerProductTimelineItem = Annotated[
    AppServerUserMessageItem
    | AppServerAgentMessageItem
    | AppServerNoticeItem
    | AppServerContextCompactionItem
    | AppServerPlanItem
    | AppServerCommandItem
    | AppServerDiffItem,
    Field(discriminator="kind"),
]


class AppServerThreadProductSnapshot(BaseModel):
    """不暴露本机路径的线程产品快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    model_id: str | None = Field(default=None, max_length=128)
    model_provider: str | None = Field(default=None, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    archived: bool = False
    created_at: float | None = Field(default=None, ge=0)
    updated_at: float | None = Field(default=None, ge=0)
    recency_at: float | None = Field(default=None, ge=0)


class AppServerTurnProductSnapshot(BaseModel):
    """线程读取结果中的 turn 与时间线正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=64)
    started_at: float | None = Field(default=None, ge=0)
    completed_at: float | None = Field(default=None, ge=0)
    error_message: str | None = Field(default=None, max_length=512)
    items: tuple[AppServerProductTimelineItem, ...]


class AppServerThreadReadProductResult(BaseModel):
    """thread/read 经审核并去除本机敏感字段后的强类型结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["thread.read"] = "thread.read"
    thread: AppServerThreadProductSnapshot
    turns: tuple[AppServerTurnProductSnapshot, ...]
    history_status: Literal["complete", "omitted_too_large"] = "complete"


class AppServerProductNotificationHeader(BaseModel):
    """产品 notification 公共头字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["app_server_product_notification"] = APP_SERVER_PRODUCT_NOTIFICATION_KIND
    schema_version: Literal["1.0"] = APP_SERVER_PRODUCT_NOTIFICATION_SCHEMA_VERSION
    method: AppServerNotificationName
    emitted_at_ms: int | None = Field(default=None, ge=0)


class AppServerThreadChangedDetail(BaseModel):
    """线程建立或状态变更。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["thread_changed"] = "thread_changed"
    thread: AppServerThreadProductSnapshot


class AppServerThreadMetadataChangedDetail(BaseModel):
    """线程名称或归档状态变化。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["thread_metadata_changed"] = "thread_metadata_changed"
    thread_id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    archived: bool | None = None


class AppServerTurnChangedDetail(BaseModel):
    """turn 建立或完成。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["turn_changed"] = "turn_changed"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=64)


class AppServerItemChangedDetail(BaseModel):
    """item 建立或完成的可渲染产品正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["item_changed"] = "item_changed"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    status: Literal["started", "completed"]
    item: AppServerProductTimelineItem


class AppServerItemDeltaDetail(BaseModel):
    """允许合并的 item 文本 delta。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["item_delta"] = "item_delta"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    item_id: str = Field(min_length=1, max_length=256)
    delta: str = Field(max_length=APP_SERVER_PRODUCT_MAX_DELTA_CHARS)


class AppServerPlanChangedDetail(BaseModel):
    """plan 的完整有界结构化正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["plan_changed"] = "plan_changed"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    explanation: str | None = Field(default=None, max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    steps: tuple[AppServerPlanStep, ...]


class AppServerDiffChangedDetail(BaseModel):
    """diff 的完整有界正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["diff_changed"] = "diff_changed"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    unified_diff: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    truncated: bool


class AppServerWarningDetail(BaseModel):
    """脱敏 warning/error。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["warning"] = "warning"
    reason_code: str = Field(min_length=1, max_length=128)
    error_code: str | None = Field(default=None, max_length=128)


AppServerProductNotificationDetail = Annotated[
    AppServerThreadChangedDetail
    | AppServerThreadMetadataChangedDetail
    | AppServerTurnChangedDetail
    | AppServerItemChangedDetail
    | AppServerItemDeltaDetail
    | AppServerPlanChangedDetail
    | AppServerDiffChangedDetail
    | AppServerWarningDetail,
    Field(discriminator="kind"),
]


class AppServerProductNotification(BaseModel):
    """App Server notification 公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: AppServerProductNotificationHeader
    detail: AppServerProductNotificationDetail


class AppServerProtocolAdaptationResult(BaseModel):
    """adapter 成功结果或稳定 warning。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    notification: AppServerProductNotification | None = None
    warning_reason: AppServerProtocolWarningReason | None = None
    warning_method: str | None = Field(default=None, max_length=128)
