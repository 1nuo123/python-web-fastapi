"""浏览器与 Agent 流式链路的确定性故障注入计划。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TypeVar

from src.core.codex_contract.realtime_event_contract import CodexRealtimeEvent


class CodexNetworkFault(StrEnum):
    """WP-00 要求覆盖的网络故障类型。"""

    OFFLINE = "offline"
    DELAYED = "delayed"
    DUPLICATE_RESPONSE = "duplicate_response"
    DISCONNECT_AFTER_CONNECT = "disconnect_after_connect"
    CURSOR_GAP = "cursor_gap"
    EPOCH_CHANGE = "epoch_change"


@dataclass(frozen=True, slots=True)
class CodexNetworkFaultPlan:
    """不触碰真实网络的故障注入配置。"""

    fault: CodexNetworkFault
    delay_seconds: float = 0.0
    duplicate_count: int = 1

    def validate(self) -> None:
        """校验故障参数边界。"""

        if self.delay_seconds < 0:
            raise ValueError("故障延迟不能为负数。")
        if self.duplicate_count < 1:
            raise ValueError("重复响应次数必须大于零。")

    def apply(self, events: Iterable[_EventT]) -> tuple[_EventT, ...]:
        """对确定性事件序列施加可复现的重复或丢弃语义。"""

        self.validate()
        values = tuple(events)
        if self.fault in {CodexNetworkFault.OFFLINE, CodexNetworkFault.DISCONNECT_AFTER_CONNECT}:
            return ()
        if self.fault is CodexNetworkFault.DUPLICATE_RESPONSE:
            return values * self.duplicate_count
        if self.fault is CodexNetworkFault.CURSOR_GAP:
            return values[1:]
        return values

    def apply_realtime_events(
        self,
        events: Iterable[CodexRealtimeEvent],
    ) -> tuple[CodexRealtimeEvent, ...]:
        """注入需要修改实时事件头的延迟和 epoch 故障，绝不触碰真实网络。"""

        values = self.apply(events)
        if self.fault is CodexNetworkFault.DELAYED:
            return tuple(
                event.model_copy(
                    update={
                        "header": event.header.model_copy(
                            update={
                                "occurred_at": event.header.occurred_at
                                + timedelta(seconds=self.delay_seconds)
                            }
                        )
                    }
                )
                for event in values
            )
        if self.fault is CodexNetworkFault.EPOCH_CHANGE and values:
            first_event, *remaining_events = values
            replacement_epoch = f"{first_event.header.stream_epoch}-fault"
            return (
                first_event,
                *(
                    event.model_copy(
                        update={
                            "header": event.header.model_copy(
                                update={"stream_epoch": replacement_epoch}
                            )
                        }
                    )
                    for event in remaining_events
                ),
            )
        return values


_EventT = TypeVar("_EventT")
