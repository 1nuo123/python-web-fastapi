"""Codex 浏览器客户端性能诊断的封闭契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODEX_CLIENT_PERFORMANCE_SCHEMA_VERSION: Final = "1.0"
CLIENT_PERFORMANCE_EVENT_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
CLIENT_PERFORMANCE_VALUE_MAXIMUM: Final = 1_048_576.0


class CodexClientPerformanceSource(StrEnum):
    """性能测量的服务端归属来源，禁止由浏览器自由指定。"""

    SCROLL = "scroll"
    REALTIME = "realtime"
    RENDERING = "rendering"
    TURN = "turn"
    CONNECTION = "connection"
    AUTH = "auth"
    APPROVAL = "approval"
    PWA = "pwa"


class CodexClientPerformanceMetric(StrEnum):
    """允许进入诊断链路的固定性能测量名称。"""

    SCROLL_STATE_TRANSITION = "scroll_state_transition"
    SCROLL_UNEXPECTED_DETACH = "scroll_unexpected_detach"
    SCROLL_ANCHOR_CORRECTION_PIXELS = "scroll_anchor_correction_pixels"
    REALTIME_BATCH_EVENT_COUNT = "realtime_batch_event_count"
    REALTIME_BATCH_BYTES = "realtime_batch_bytes"
    REDUCER_DURATION_MILLISECONDS = "reducer_duration_milliseconds"
    MARKDOWN_DURATION_MILLISECONDS = "markdown_duration_milliseconds"
    LONG_TASK_DURATION_MILLISECONDS = "long_task_duration_milliseconds"
    APPROXIMATE_FPS = "approximate_fps"
    SEND_ACK_LATENCY_MILLISECONDS = "send_ack_latency_milliseconds"
    DUPLICATE_OPERATION = "duplicate_operation"
    RECONNECT_ATTEMPT = "reconnect_attempt"
    CURSOR_GAP = "cursor_gap"
    SNAPSHOT_REPLAY_EVENT_COUNT = "snapshot_replay_event_count"
    AUTH_TERMINAL = "auth_terminal"
    STALLED_TRANSITION = "stalled_transition"
    APPROVAL_DELIVERY_LATENCY_MILLISECONDS = "approval_delivery_latency_milliseconds"
    PWA_LEGACY_CONTROLLER = "pwa_legacy_controller"
    PWA_LEGACY_CACHE = "pwa_legacy_cache"


class CodexClientPerformanceObservation(StrEnum):
    """性能事件的封闭上下文，不允许以自由文本传递原因或状态。"""

    FOLLOWING_TO_DETACHED = "following_to_detached"
    DETACHED_TO_FOLLOWING = "detached_to_following"
    RESTORING_TO_FOLLOWING = "restoring_to_following"
    UNEXPECTED_DETACH = "unexpected_detach"
    ANCHOR_CORRECTED = "anchor_corrected"
    NORMAL_BATCH = "normal_batch"
    BARRIER_BATCH = "barrier_batch"
    OBSERVED = "observed"
    DETECTED = "detected"
    ACKNOWLEDGED = "acknowledged"
    DUPLICATE = "duplicate"
    NETWORK_ONLINE = "network_online"
    VISIBILITY_RESUME = "visibility_resume"
    SOCKET_CLOSED = "socket_closed"
    RETRY_TIMER = "retry_timer"
    REPLAYED = "replayed"
    TERMINAL = "terminal"
    STALLED = "stalled"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    LEGACY_CONTROLLER_DETECTED = "legacy_controller_detected"
    LEGACY_CACHE_DETECTED = "legacy_cache_detected"


class CodexClientPerformanceUnit(StrEnum):
    """数值样本的固定单位，避免前端传入含义不明的值。"""

    COUNT = "count"
    BYTES = "bytes"
    MILLISECONDS = "milliseconds"
    PIXELS = "pixels"
    FRAMES_PER_SECOND = "frames_per_second"


@dataclass(frozen=True, slots=True)
class CodexClientPerformanceMetricDefinition:
    """一个性能测量的来源、单位、上限和有效观测值。"""

    source: CodexClientPerformanceSource
    unit: CodexClientPerformanceUnit
    maximum_value: float
    allowed_observations: frozenset[CodexClientPerformanceObservation]


CODEX_CLIENT_PERFORMANCE_METRIC_DEFINITIONS: Final = {
    CodexClientPerformanceMetric.SCROLL_STATE_TRANSITION: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.SCROLL,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset(
            {
                CodexClientPerformanceObservation.FOLLOWING_TO_DETACHED,
                CodexClientPerformanceObservation.DETACHED_TO_FOLLOWING,
                CodexClientPerformanceObservation.RESTORING_TO_FOLLOWING,
            }
        ),
    ),
    CodexClientPerformanceMetric.SCROLL_UNEXPECTED_DETACH: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.SCROLL,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.UNEXPECTED_DETACH}),
    ),
    CodexClientPerformanceMetric.SCROLL_ANCHOR_CORRECTION_PIXELS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.SCROLL,
        unit=CodexClientPerformanceUnit.PIXELS,
        maximum_value=CLIENT_PERFORMANCE_VALUE_MAXIMUM,
        allowed_observations=frozenset({CodexClientPerformanceObservation.ANCHOR_CORRECTED}),
    ),
    CodexClientPerformanceMetric.REALTIME_BATCH_EVENT_COUNT: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.REALTIME,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=64.0,
        allowed_observations=frozenset(
            {
                CodexClientPerformanceObservation.NORMAL_BATCH,
                CodexClientPerformanceObservation.BARRIER_BATCH,
            }
        ),
    ),
    CodexClientPerformanceMetric.REALTIME_BATCH_BYTES: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.REALTIME,
        unit=CodexClientPerformanceUnit.BYTES,
        maximum_value=65_536.0,
        allowed_observations=frozenset(
            {
                CodexClientPerformanceObservation.NORMAL_BATCH,
                CodexClientPerformanceObservation.BARRIER_BATCH,
            }
        ),
    ),
    CodexClientPerformanceMetric.REDUCER_DURATION_MILLISECONDS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.RENDERING,
        unit=CodexClientPerformanceUnit.MILLISECONDS,
        maximum_value=60_000.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.OBSERVED}),
    ),
    CodexClientPerformanceMetric.MARKDOWN_DURATION_MILLISECONDS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.RENDERING,
        unit=CodexClientPerformanceUnit.MILLISECONDS,
        maximum_value=60_000.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.OBSERVED}),
    ),
    CodexClientPerformanceMetric.LONG_TASK_DURATION_MILLISECONDS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.RENDERING,
        unit=CodexClientPerformanceUnit.MILLISECONDS,
        maximum_value=60_000.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.DETECTED}),
    ),
    CodexClientPerformanceMetric.APPROXIMATE_FPS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.RENDERING,
        unit=CodexClientPerformanceUnit.FRAMES_PER_SECOND,
        maximum_value=240.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.OBSERVED}),
    ),
    CodexClientPerformanceMetric.SEND_ACK_LATENCY_MILLISECONDS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.TURN,
        unit=CodexClientPerformanceUnit.MILLISECONDS,
        maximum_value=300_000.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.ACKNOWLEDGED}),
    ),
    CodexClientPerformanceMetric.DUPLICATE_OPERATION: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.TURN,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.DUPLICATE}),
    ),
    CodexClientPerformanceMetric.RECONNECT_ATTEMPT: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.CONNECTION,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset(
            {
                CodexClientPerformanceObservation.NETWORK_ONLINE,
                CodexClientPerformanceObservation.VISIBILITY_RESUME,
                CodexClientPerformanceObservation.SOCKET_CLOSED,
                CodexClientPerformanceObservation.RETRY_TIMER,
            }
        ),
    ),
    CodexClientPerformanceMetric.CURSOR_GAP: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.CONNECTION,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.DETECTED}),
    ),
    CodexClientPerformanceMetric.SNAPSHOT_REPLAY_EVENT_COUNT: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.CONNECTION,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=10_000.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.REPLAYED}),
    ),
    CodexClientPerformanceMetric.AUTH_TERMINAL: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.AUTH,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.TERMINAL}),
    ),
    CodexClientPerformanceMetric.STALLED_TRANSITION: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.TURN,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.STALLED}),
    ),
    CodexClientPerformanceMetric.APPROVAL_DELIVERY_LATENCY_MILLISECONDS: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.APPROVAL,
        unit=CodexClientPerformanceUnit.MILLISECONDS,
        maximum_value=300_000.0,
        allowed_observations=frozenset(
            {
                CodexClientPerformanceObservation.DELIVERED,
                CodexClientPerformanceObservation.DELIVERY_FAILED,
            }
        ),
    ),
    CodexClientPerformanceMetric.PWA_LEGACY_CONTROLLER: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.PWA,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset(
            {CodexClientPerformanceObservation.LEGACY_CONTROLLER_DETECTED}
        ),
    ),
    CodexClientPerformanceMetric.PWA_LEGACY_CACHE: CodexClientPerformanceMetricDefinition(
        source=CodexClientPerformanceSource.PWA,
        unit=CodexClientPerformanceUnit.COUNT,
        maximum_value=1.0,
        allowed_observations=frozenset({CodexClientPerformanceObservation.LEGACY_CACHE_DETECTED}),
    ),
}


class CodexClientPerformanceHeader(BaseModel):
    """性能诊断的版本、事件标识与发生时间头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["client_performance"] = "client_performance"
    schema_version: Literal["1.0"] = CODEX_CLIENT_PERFORMANCE_SCHEMA_VERSION
    event_id: str = Field(pattern=CLIENT_PERFORMANCE_EVENT_ID_PATTERN)
    occurred_at: datetime


class CodexClientPerformanceDetail(BaseModel):
    """仅由固定枚举和受限数值组成的性能样本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["client_performance_detail"] = "client_performance_detail"
    schema_version: Literal["1.0"] = CODEX_CLIENT_PERFORMANCE_SCHEMA_VERSION
    metric: CodexClientPerformanceMetric
    observation: CodexClientPerformanceObservation
    unit: CodexClientPerformanceUnit
    value: float = Field(ge=0, le=CLIENT_PERFORMANCE_VALUE_MAXIMUM)

    @model_validator(mode="after")
    def validate_metric_definition(self) -> Self:
        """从固定词表校验观测值、单位和数值范围，防止任意数据进入日志。"""

        definition = CODEX_CLIENT_PERFORMANCE_METRIC_DEFINITIONS[self.metric]
        if not isfinite(self.value):
            raise ValueError("客户端性能数值必须是有限数。")
        if self.unit is not definition.unit:
            raise ValueError("客户端性能数值单位与测量类型不一致。")
        if self.observation not in definition.allowed_observations:
            raise ValueError("客户端性能观测值与测量类型不一致。")
        if self.value > definition.maximum_value:
            raise ValueError("客户端性能数值超过测量类型上限。")
        return self


class CodexClientPerformanceEnvelope(BaseModel):
    """浏览器和服务端共用的无正文性能诊断信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexClientPerformanceHeader
    detail: CodexClientPerformanceDetail

    @model_validator(mode="after")
    def validate_schema_version(self) -> Self:
        """拒绝头部与详情版本不一致，确保收集范围不会被宽松升级扩大。"""

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("客户端性能诊断头部与详情版本必须一致。")
        return self


class CodexClientPerformanceReceipt(BaseModel):
    """性能诊断接收回执，不包含用户、会话或限流信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recorded: bool
