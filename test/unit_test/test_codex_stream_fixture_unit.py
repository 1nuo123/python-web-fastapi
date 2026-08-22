"""Codex 流式回放夹具、固定时间与故障注入的确定性单元测试。"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.core.codex_contract.feature_flags_contract import CodexExperienceFeatureFlags
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType
from src.infrastructure.testing.fixed_time_source import FixedTimeSource
from test.fixtures.codex_network_faults import CodexNetworkFault, CodexNetworkFaultPlan
from test.fixtures.codex_stream_fixture import (
    CodexFixtureEventKind,
    CodexFixtureStep,
    CodexStreamFixture,
    build_default_feature_flags,
)


@pytest.mark.parametrize("rate_hz", [1, 10, 30, 100])
def test_stream_fixture_replay_is_repeatable_at_supported_rates(rate_hz: int) -> None:
    """相同输入和固定时钟必须生成相同顺序，并以指定频率推进事件时间。"""

    initial = datetime(2026, 8, 19, tzinfo=UTC)
    fixture = CodexStreamFixture()

    first_replay = fixture.replay(clock=FixedTimeSource(initial), rate_hz=rate_hz)
    second_replay = fixture.replay(clock=FixedTimeSource(initial), rate_hz=rate_hz)

    assert first_replay == second_replay
    assert [event.header.cursor for event in first_replay] == ["1", "2", "3", "4", "5"]
    assert first_replay[1].header.occurred_at - first_replay[0].header.occurred_at == timedelta(
        seconds=1 / rate_hz
    )


def test_stream_fixture_covers_product_event_categories() -> None:
    """默认夹具必须覆盖流式正文、审批、终态和可恢复错误。"""

    events = CodexStreamFixture().replay()

    assert [event.header.detail_kind for event in events] == [
        CodexRealtimeEventType.ITEM_DELTA,
        CodexRealtimeEventType.ITEM_DELTA,
        CodexRealtimeEventType.PROTOCOL_WARNING,
        CodexRealtimeEventType.TURN_COMPLETED,
        CodexRealtimeEventType.STREAM_GAP_DETECTED,
    ]


def test_stream_fixture_preserves_deliberately_out_of_order_steps() -> None:
    """乱序必须作为输入显式保留，供 reducer 恢复路径验证而非夹具静默排序。"""

    events = CodexStreamFixture(
        steps=(
            CodexFixtureStep(CodexFixtureEventKind.DELTA, "later", "2"),
            CodexFixtureStep(CodexFixtureEventKind.DELTA, "earlier", "1"),
        )
    ).replay()

    assert [event.header.cursor for event in events] == ["2", "1"]


def test_network_fault_plan_injects_repeatable_transport_failures() -> None:
    """离线、断连、重复和 cursor 缺口均由纯夹具控制，不建立网络连接。"""

    events = CodexStreamFixture().replay()

    assert CodexNetworkFaultPlan(CodexNetworkFault.OFFLINE).apply(events) == ()
    assert CodexNetworkFaultPlan(CodexNetworkFault.DISCONNECT_AFTER_CONNECT).apply(events) == ()
    assert (
        CodexNetworkFaultPlan(
            CodexNetworkFault.DUPLICATE_RESPONSE,
            duplicate_count=2,
        ).apply(events)
        == events * 2
    )
    assert CodexNetworkFaultPlan(CodexNetworkFault.CURSOR_GAP).apply(events) == events[1:]


def test_network_fault_plan_changes_realtime_delay_and_epoch_without_sleeping() -> None:
    """延迟和 epoch 变化必须可直接观察，测试不等待真实时钟或 socket。"""

    events = CodexStreamFixture().replay()

    delayed = CodexNetworkFaultPlan(
        CodexNetworkFault.DELAYED,
        delay_seconds=2.5,
    ).apply_realtime_events(events)
    changed_epoch = CodexNetworkFaultPlan(CodexNetworkFault.EPOCH_CHANGE).apply_realtime_events(
        events
    )

    assert delayed[0].header.occurred_at == events[0].header.occurred_at + timedelta(seconds=2.5)
    assert changed_epoch[0].header.stream_epoch == events[0].header.stream_epoch
    assert {event.header.stream_epoch for event in changed_epoch[1:]} == {
        f"{events[0].header.stream_epoch}-fault"
    }


def test_feature_flags_are_closed_and_default_to_legacy_paths() -> None:
    """体验开关必须默认关闭，并拒绝未声明配置以防静默启用新路径。"""

    assert build_default_feature_flags() == CodexExperienceFeatureFlags()
    assert CodexExperienceFeatureFlags().model_dump() == {
        "codex_scroll_controller_v2": False,
        "codex_realtime_batch_v2": False,
        "codex_authority_recovery_v2": False,
    }
    with pytest.raises(ValidationError):
        CodexExperienceFeatureFlags.model_validate({"unknown_flag": True})
