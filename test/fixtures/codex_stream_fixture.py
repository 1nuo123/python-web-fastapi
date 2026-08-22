"""可编程 Codex 流式事件夹具与确定性回放工具。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from src.core.codex_contract.feature_flags_contract import CodexExperienceFeatureFlags
from src.core.codex_contract.realtime_event_contract import (
    CodexItemDeltaDetail,
    CodexProtocolWarningDetail,
    CodexRealtimeEvent,
    CodexRealtimeEventDetail,
    CodexRealtimeEventHeader,
    CodexRealtimeEventType,
    CodexStreamGapDetail,
    CodexTurnChangedDetail,
)
from src.core.codex_contract.thread_contract import CodexTurnSnapshot
from src.infrastructure.testing.fixed_time_source import FixedTimeSource


class CodexFixtureEventKind(StrEnum):
    """回放夹具覆盖的产品事件类别。"""

    DELTA = "delta"
    COMMAND_OUTPUT = "command_output"
    APPROVAL = "approval"
    TERMINAL = "terminal"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CodexFixtureStep:
    """单个可重复回放的高层事件步骤。"""

    kind: CodexFixtureEventKind
    payload: str
    cursor: str


class CodexStreamFixture:
    """用固定时间生成同一顺序、同一游标的实时事件。"""

    def __init__(
        self,
        *,
        host_id: UUID | None = None,
        stream_epoch: str = "fixture-epoch-1",
        steps: Iterable[CodexFixtureStep] | None = None,
    ) -> None:
        self.host_id = host_id or UUID("00000000-0000-0000-0000-000000000001")
        self.stream_epoch = stream_epoch
        self.steps = tuple(steps or self._default_steps())

    def replay(
        self,
        *,
        clock: FixedTimeSource | None = None,
        rate_hz: int = 30,
    ) -> tuple[CodexRealtimeEvent, ...]:
        """按固定频率生成事件；频率只影响时间，不改变顺序。"""

        if rate_hz <= 0:
            raise ValueError("回放频率必须大于零。")
        source = clock or FixedTimeSource()
        events: list[CodexRealtimeEvent] = []
        for step in self.steps:
            detail_kind, detail = self._build_detail(step)
            events.append(
                CodexRealtimeEvent(
                    header=CodexRealtimeEventHeader(
                        event_id=f"fixture-event-{step.cursor}",
                        occurred_at=source.now(),
                        host_id=self.host_id,
                        detail_kind=detail_kind,
                        stream_epoch=self.stream_epoch,
                        cursor=step.cursor,
                    ),
                    detail=detail,
                )
            )
            source.advance(1 / rate_hz)
        return tuple(events)

    @staticmethod
    def _build_detail(
        step: CodexFixtureStep,
    ) -> tuple[CodexRealtimeEventType, CodexRealtimeEventDetail]:
        """把测试语义映射为现有的受校验产品事件。"""

        if step.kind in {
            CodexFixtureEventKind.DELTA,
            CodexFixtureEventKind.COMMAND_OUTPUT,
        }:
            return (
                CodexRealtimeEventType.ITEM_DELTA,
                CodexItemDeltaDetail(
                    item_id="fixture-item-1",
                    thread_id="fixture-thread-1",
                    delta=step.payload,
                ),
            )
        if step.kind is CodexFixtureEventKind.APPROVAL:
            return (
                CodexRealtimeEventType.PROTOCOL_WARNING,
                CodexProtocolWarningDetail(warning=f"approval:{step.payload}"),
            )
        if step.kind is CodexFixtureEventKind.TERMINAL:
            return (
                CodexRealtimeEventType.TURN_COMPLETED,
                CodexTurnChangedDetail(
                    kind="turn.completed",
                    turn=CodexTurnSnapshot(
                        turn_id="fixture-turn-1",
                        thread_id="fixture-thread-1",
                        status="completed",
                    ),
                ),
            )
        return (
            CodexRealtimeEventType.STREAM_GAP_DETECTED,
            CodexStreamGapDetail(reason=step.payload),
        )

    @staticmethod
    def _default_steps() -> tuple[CodexFixtureStep, ...]:
        return (
            CodexFixtureStep(CodexFixtureEventKind.DELTA, "first delta", "1"),
            CodexFixtureStep(CodexFixtureEventKind.COMMAND_OUTPUT, "command output", "2"),
            CodexFixtureStep(CodexFixtureEventKind.APPROVAL, "approval opened", "3"),
            CodexFixtureStep(CodexFixtureEventKind.TERMINAL, "completed", "4"),
            CodexFixtureStep(CodexFixtureEventKind.ERROR, "fixture_gap", "5"),
        )


def build_default_feature_flags() -> CodexExperienceFeatureFlags:
    """返回测试默认关闭的体验优化开关。"""

    return CodexExperienceFeatureFlags()
