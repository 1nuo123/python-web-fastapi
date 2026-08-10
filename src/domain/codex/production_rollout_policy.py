"""Codex 生产 rollout 纯策略。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.core.codex_contract.production_hardening_contract import CodexSloPolicyDetail


class CodexRolloutReasonCode(StrEnum):
    """rollout 决策原因码。"""

    PAUSE_DISABLED = "rollout_pause_disabled"
    HOST_ONLINE_SLO_EXCEEDED = "host_online_slo_exceeded"
    COMMAND_ACK_SLO_EXCEEDED = "command_ack_slo_exceeded"
    RECONNECT_SLO_EXCEEDED = "reconnect_slo_exceeded"
    EVENT_GAP_SLO_EXCEEDED = "event_gap_slo_exceeded"
    ERROR_BUDGET_EXCEEDED = "error_budget_exceeded"
    SLO_WITHIN_BUDGET = "slo_within_budget"


@dataclass(frozen=True, slots=True)
class CodexSloObservation:
    """不包含高基数标识的 SLO 观测值。"""

    host_online_p95_milliseconds: int
    command_ack_p95_milliseconds: int
    reconnect_p95_milliseconds: int
    event_gap_count: int
    error_budget_consumed_percent: float


@dataclass(frozen=True, slots=True)
class CodexRolloutDecision:
    """rollout 是否允许继续的可审计决定。"""

    allowed: bool
    reason_code: CodexRolloutReasonCode


class CodexProductionRolloutPolicy:
    """任一 SLO 或错误预算超限时暂停扩大更新渠道。"""

    def evaluate(
        self,
        *,
        policy: CodexSloPolicyDetail,
        observation: CodexSloObservation,
    ) -> CodexRolloutDecision:
        """按冻结阈值评估当前 rollout。"""

        if not policy.pause_rollout_when_exceeded:
            return CodexRolloutDecision(True, CodexRolloutReasonCode.PAUSE_DISABLED)
        if observation.host_online_p95_milliseconds > policy.host_online_p95_milliseconds:
            return CodexRolloutDecision(
                False,
                CodexRolloutReasonCode.HOST_ONLINE_SLO_EXCEEDED,
            )
        if observation.command_ack_p95_milliseconds > policy.command_ack_p95_milliseconds:
            return CodexRolloutDecision(
                False,
                CodexRolloutReasonCode.COMMAND_ACK_SLO_EXCEEDED,
            )
        if observation.reconnect_p95_milliseconds > policy.reconnect_p95_milliseconds:
            return CodexRolloutDecision(
                False,
                CodexRolloutReasonCode.RECONNECT_SLO_EXCEEDED,
            )
        if observation.event_gap_count > policy.maximum_event_gap_count:
            return CodexRolloutDecision(
                False,
                CodexRolloutReasonCode.EVENT_GAP_SLO_EXCEEDED,
            )
        if observation.error_budget_consumed_percent > policy.error_budget_percent:
            return CodexRolloutDecision(
                False,
                CodexRolloutReasonCode.ERROR_BUDGET_EXCEEDED,
            )
        return CodexRolloutDecision(True, CodexRolloutReasonCode.SLO_WITHIN_BUDGET)
