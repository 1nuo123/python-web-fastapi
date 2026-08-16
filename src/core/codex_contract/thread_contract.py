"""Codex 会话索引与时间线公共契约。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODEX_THREAD_TITLE_MAX_LENGTH: Final = 256
CODEX_THREAD_MODEL_MAX_LENGTH: Final = 128
CODEX_THREAD_STATUS_MAX_LENGTH: Final = 32
CODEX_TIMELINE_TEXT_MAX_LENGTH: Final = 1_048_576
CODEX_TIMELINE_COMMAND_MAX_LENGTH: Final = 1_048_576
CODEX_TIMELINE_ITEM_SCHEMA_VERSION: Final = "1.0"
CODEX_CONVERSATION_CURSOR_SCHEMA_VERSION: Final = "1.0"
CODEX_CONVERSATION_PAGE_LIMIT_DEFAULT: Final = 50
CODEX_CONVERSATION_PAGE_LIMIT_MINIMUM: Final = 1
CODEX_CONVERSATION_PAGE_LIMIT_MAXIMUM: Final = 200


class CodexThreadTitleSource(StrEnum):
    """会话标题的封闭来源集合。"""

    MANUAL = "manual"
    APP_SERVER = "app_server"
    FIRST_USER_MESSAGE = "first_user_message"
    NEW_CONVERSATION = "new_conversation"


class CodexThreadStatus(StrEnum):
    """控制面可稳定展示的会话状态。"""

    IDLE = "idle"
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    UNKNOWN = "unknown"
    ARCHIVED = "archived"


class CodexConversationListMode(StrEnum):
    """会话列表的封闭展示模式。"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    SEARCH = "search"


class CodexThreadHistoryStatus(StrEnum):
    """会话历史正文装载状态。"""

    COMPLETE = "complete"
    NOT_REQUESTED = "not_requested"
    OMITTED_TOO_LARGE = "omitted_too_large"
    NOT_AVAILABLE_YET = "not_available_yet"


class CodexTimelineItemKind(StrEnum):
    """时间线扩展字段种类。"""

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    PLAN = "plan"
    COMMAND = "command"
    DIFF = "diff"
    APPROVAL = "approval"
    NOTICE = "notice"
    CONTEXT_COMPACTION = "context_compaction"


class CodexTimelineItemStatus(StrEnum):
    """时间线条目状态。"""

    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"


class CodexActiveTurnUpdateMode(StrEnum):
    """实时状态更新对活动 turn 定位的处理方式。"""

    PRESERVE = "preserve"
    SET = "set"
    CLEAR = "clear"


class CodexPlanStepStatus(StrEnum):
    """结构化计划步骤状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CodexPlanStepSnapshot(BaseModel):
    """浏览器可直接渲染的计划步骤。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step: str = Field(min_length=1, max_length=4_096)
    status: CodexPlanStepStatus


class CodexDiffChangeKind(StrEnum):
    """文件变更类型。"""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class CodexDiffLineKind(StrEnum):
    """Diff 行类型。"""

    CONTEXT = "context"
    ADDITION = "addition"
    DELETION = "deletion"


class CodexDiffLineSnapshot(BaseModel):
    """携带旧、新行号的单行 Diff。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CodexDiffLineKind
    content: str = Field(max_length=4_096)
    old_line_number: int | None = Field(default=None, ge=1)
    new_line_number: int | None = Field(default=None, ge=1)


class CodexDiffHunkSnapshot(BaseModel):
    """一个可独立虚拟化的 Diff hunk。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: str = Field(min_length=1, max_length=512)
    old_start: int = Field(ge=0)
    new_start: int = Field(ge=0)
    lines: tuple[CodexDiffLineSnapshot, ...]


class CodexDiffFileSnapshot(BaseModel):
    """单文件结构化 Diff。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_024)
    old_path: str | None = Field(default=None, max_length=1_024)
    change_kind: CodexDiffChangeKind
    binary: bool
    large: bool
    truncated: bool
    hunks: tuple[CodexDiffHunkSnapshot, ...]


class CodexDiffSnapshot(BaseModel):
    """一次 turn 的结构化文件变更集合。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files: tuple[CodexDiffFileSnapshot, ...]
    total_characters: int = Field(ge=0)
    truncated: bool


class CodexConversationSortKey(BaseModel):
    """完整表达会话稳定排序顺序的键。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_pinned: bool
    recency_at: datetime
    created_at: datetime
    upstream_thread_id: str = Field(min_length=1, max_length=256)


class CodexThreadRuntimeStateUpdate(BaseModel):
    """不会覆盖标题与活动时间的会话运行状态局部更新。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CodexThreadStatus | None = None
    active_turn_mode: CodexActiveTurnUpdateMode = CodexActiveTurnUpdateMode.PRESERVE
    active_turn_id: str | None = Field(default=None, max_length=256)
    archived: bool | None = None
    synchronized_at: datetime

    @model_validator(mode="after")
    def validate_active_turn_update(self) -> Self:
        """活动 turn 更新模式必须与定位字段一致。"""

        if self.active_turn_mode is CodexActiveTurnUpdateMode.SET and not self.active_turn_id:
            raise ValueError("设置活动turn时必须提供active_turn_id。")
        if self.active_turn_mode is not CodexActiveTurnUpdateMode.SET and self.active_turn_id:
            raise ValueError("仅设置活动turn模式允许提供active_turn_id。")
        return self


class CodexThreadIndexSnapshot(BaseModel):
    """控制面会话索引；不包含消息、代码或 Diff 正文。

    :ivar display_name: 非空会话标题。
    :ivar title_source: 标题权威来源。
    :ivar recency_at: 上游定义的真实活动时间。
    :ivar last_synced_at: 控制面最近同步时间，不参与排序。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_index_id: UUID
    host_id: UUID
    workspace_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    upstream_thread_id: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=CODEX_THREAD_TITLE_MAX_LENGTH)
    title_source: CodexThreadTitleSource
    model: str | None = Field(default=None, max_length=CODEX_THREAD_MODEL_MAX_LENGTH)
    model_provider: str | None = Field(default=None, max_length=CODEX_THREAD_MODEL_MAX_LENGTH)
    reasoning_effort: str | None = Field(default=None, max_length=64)
    status: CodexThreadStatus
    active_turn_id: str | None = Field(default=None, max_length=256)
    archived: bool
    is_pinned: bool
    source_kind: str | None = Field(default=None, max_length=64)
    created_at: datetime
    recency_at: datetime
    updated_at: datetime
    last_synced_at: datetime

    def build_sort_key(self) -> CodexConversationSortKey:
        """构造不包含同步时间的稳定排序键。"""

        return CodexConversationSortKey(
            is_pinned=self.is_pinned,
            recency_at=self.recency_at,
            created_at=self.created_at,
            upstream_thread_id=self.upstream_thread_id,
        )


class CodexConversationListQuery(BaseModel):
    """会话列表过滤、分页与归档条件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID | None = None
    archived: bool = False
    search_term: str | None = Field(default=None, min_length=1, max_length=128)
    cursor: str | None = Field(default=None, max_length=2_048)
    limit: int = Field(
        default=CODEX_CONVERSATION_PAGE_LIMIT_DEFAULT,
        ge=CODEX_CONVERSATION_PAGE_LIMIT_MINIMUM,
        le=CODEX_CONVERSATION_PAGE_LIMIT_MAXIMUM,
    )

    @model_validator(mode="after")
    def normalize_search_term(self) -> Self:
        """拒绝只包含空白的搜索条件。"""

        if self.search_term is not None and not self.search_term.strip():
            raise ValueError("会话搜索条件不能为空白。")
        return self

    def build_identity_digest(self) -> str:
        """生成绑定过滤条件但不包含游标与页容量的摘要。"""

        canonical = json.dumps(
            {
                "workspace_id": str(self.workspace_id) if self.workspace_id else None,
                "archived": self.archived,
                "search_term": self.search_term.strip().casefold() if self.search_term else None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CodexConversationCursorHeader(BaseModel):
    """会话键集游标公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_conversation_cursor"] = "codex_conversation_cursor"
    schema_version: Literal["1.0"] = CODEX_CONVERSATION_CURSOR_SCHEMA_VERSION
    detail_kind: Literal["conversation_sort_key"] = "conversation_sort_key"


class CodexConversationCursorDetail(BaseModel):
    """包含完整稳定排序键的游标扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conversation_sort_key"] = "conversation_sort_key"
    schema_version: Literal["1.0"] = CODEX_CONVERSATION_CURSOR_SCHEMA_VERSION
    query_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_pinned: bool
    recency_at: datetime
    created_at: datetime
    upstream_thread_id: str = Field(min_length=1, max_length=256)


class CodexConversationCursor(BaseModel):
    """可验证、可绑定查询条件的会话键集游标。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexConversationCursorHeader = Field(default_factory=CodexConversationCursorHeader)
    detail: CodexConversationCursorDetail

    @model_validator(mode="after")
    def validate_detail_identity(self) -> Self:
        """拒绝游标头与扩展类型或版本不一致。"""

        if self.header.detail_kind != self.detail.kind:
            raise ValueError("会话游标头与扩展类型不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("会话游标头与扩展版本不一致。")
        return self

    def encode(self) -> str:
        """编码为 URL 安全且不包含填充歧义的文本。"""

        return base64.urlsafe_b64encode(self.model_dump_json().encode("utf-8")).decode("ascii")

    @classmethod
    def decode(cls, value: str) -> CodexConversationCursor:
        """解码并严格校验会话游标。"""

        try:
            payload = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
            return cls.model_validate_json(payload)
        except (UnicodeDecodeError, UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise ValueError("会话分页游标无效。") from exc


class CodexConversationPage(BaseModel):
    """稳定键集分页的会话索引响应。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[CodexThreadIndexSnapshot]
    next_cursor: str | None = Field(default=None, max_length=2_048)


class CodexConversationRenameRequest(BaseModel):
    """会话手工重命名请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str = Field(min_length=1, max_length=CODEX_THREAD_TITLE_MAX_LENGTH)


class CodexConversationPinRequest(BaseModel):
    """会话置顶偏好更新请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_pinned: bool


class CodexTurnSnapshot(BaseModel):
    """浏览器权威会话快照中的 turn。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=32)
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = Field(default=None, max_length=512)


class CodexTimelineItemHeader(BaseModel):
    """所有时间线条目共享的定位与状态字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    detail_kind: CodexTimelineItemKind
    schema_version: Literal["1.0"] = CODEX_TIMELINE_ITEM_SCHEMA_VERSION
    status: CodexTimelineItemStatus
    created_at: str | None = None


class CodexTimelineDetailBase(BaseModel):
    """时间线强类型扩展字段基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = CODEX_TIMELINE_ITEM_SCHEMA_VERSION


class CodexUserMessageTimelineDetail(CodexTimelineDetailBase):
    """用户消息扩展字段。"""

    kind: Literal["user_message"] = "user_message"
    text: str = Field(max_length=CODEX_TIMELINE_TEXT_MAX_LENGTH)


class CodexAgentMessageTimelineDetail(CodexTimelineDetailBase):
    """Agent 消息扩展字段。"""

    kind: Literal["agent_message"] = "agent_message"
    text: str = Field(max_length=CODEX_TIMELINE_TEXT_MAX_LENGTH)


class CodexNoticeTimelineDetail(CodexTimelineDetailBase):
    """通知和推理摘要扩展字段。"""

    kind: Literal["notice"] = "notice"
    label: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=CODEX_TIMELINE_TEXT_MAX_LENGTH)


class CodexContextCompactionTimelineDetail(CodexTimelineDetailBase):
    """上下文压缩产品状态扩展字段。"""

    kind: Literal["context_compaction"] = "context_compaction"
    label: Literal["上下文已压缩"] = "上下文已压缩"


class CodexPlanTimelineDetail(CodexTimelineDetailBase):
    """结构化计划扩展字段。"""

    kind: Literal["plan"] = "plan"
    explanation: str = Field(max_length=CODEX_TIMELINE_TEXT_MAX_LENGTH)
    steps: tuple[CodexPlanStepSnapshot, ...]


class CodexCommandTimelineDetail(CodexTimelineDetailBase):
    """命令及有界输出扩展字段。"""

    kind: Literal["command"] = "command"
    command: str = Field(max_length=CODEX_TIMELINE_COMMAND_MAX_LENGTH)
    output: str = Field(max_length=CODEX_TIMELINE_TEXT_MAX_LENGTH)
    exit_code: int | None = None


class CodexDiffTimelineDetail(CodexTimelineDetailBase):
    """结构化 Diff 扩展字段。"""

    kind: Literal["diff"] = "diff"
    diff: CodexDiffSnapshot


class CodexApprovalTimelineDetail(CodexTimelineDetailBase):
    """会话内审批引用扩展字段。"""

    kind: Literal["approval"] = "approval"
    approval_id: UUID
    approval_kind: str = Field(min_length=1, max_length=64)
    risk_level: str = Field(min_length=1, max_length=32)
    state: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=512)


CodexTimelineItemDetail = Annotated[
    CodexUserMessageTimelineDetail
    | CodexAgentMessageTimelineDetail
    | CodexNoticeTimelineDetail
    | CodexContextCompactionTimelineDetail
    | CodexPlanTimelineDetail
    | CodexCommandTimelineDetail
    | CodexDiffTimelineDetail
    | CodexApprovalTimelineDetail,
    Field(discriminator="kind"),
]


class CodexTimelineItemEnvelope(BaseModel):
    """时间线公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexTimelineItemHeader
    detail: CodexTimelineItemDetail

    @model_validator(mode="after")
    def validate_detail_identity(self) -> Self:
        """拒绝头部与扩展字段类型或版本不一致的条目。"""

        if self.header.detail_kind.value != self.detail.kind:
            raise ValueError("时间线条目头与扩展类型不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("时间线条目头与扩展版本不一致。")
        return self


class CodexThreadAuthoritySnapshot(BaseModel):
    """App Server 会话正文与 PostgreSQL 所有权索引的组合响应。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread: CodexThreadIndexSnapshot
    turns: list[CodexTurnSnapshot]
    items: list[CodexTimelineItemEnvelope]
    history_status: CodexThreadHistoryStatus = CodexThreadHistoryStatus.COMPLETE
    next_history_cursor: str | None = Field(default=None, max_length=512)
