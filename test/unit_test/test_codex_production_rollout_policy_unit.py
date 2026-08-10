"""Codex 生产 rollout 策略单元测试。"""

from src.core.codex_contract.production_hardening_contract import CodexSloPolicyDetail
from src.domain.codex.production_rollout_policy import (
    CodexProductionRolloutPolicy,
    CodexRolloutReasonCode,
    CodexSloObservation,
)


class TestCodexProductionRolloutPolicyUnit:
    """验证 SLO 与错误预算决策。"""

    def test_observation_whenWithinBudget_shouldAllow(self) -> None:
        decision = CodexProductionRolloutPolicy().evaluate(
            policy=CodexSloPolicyDetail(),
            observation=CodexSloObservation(100, 100, 100, 0, 0.5),
        )
        assert decision.allowed is True
        assert decision.reason_code == CodexRolloutReasonCode.SLO_WITHIN_BUDGET

    def test_observation_whenEventGapOccurs_shouldPause(self) -> None:
        decision = CodexProductionRolloutPolicy().evaluate(
            policy=CodexSloPolicyDetail(),
            observation=CodexSloObservation(100, 100, 100, 1, 0.5),
        )
        assert decision.allowed is False
        assert decision.reason_code == CodexRolloutReasonCode.EVENT_GAP_SLO_EXCEEDED
