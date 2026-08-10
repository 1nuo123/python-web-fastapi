"""Codex 生产硬化强类型策略契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.codex_contract.production_hardening_contract import (
    CODEX_ABUSE_POLICY_KIND,
    CODEX_RETENTION_POLICY_KIND,
    CODEX_SLO_POLICY_KIND,
    DAYS_PER_WEEK,
    SECONDS_PER_DAY,
    CodexAbusePolicyDetail,
    CodexCanaryStage,
    CodexProductionPolicyEnvelope,
    CodexProductionPolicyHeader,
    CodexRetentionPolicyDetail,
    CodexSloPolicyDetail,
)


class TestCodexProductionHardeningContract:
    """验证滥用防护、留存和 SLO 信封的公共头一致性。"""

    def test_policy_variants_should_round_trip_with_typed_details(self) -> None:
        policies = (
            CodexProductionPolicyEnvelope(
                header=CodexProductionPolicyHeader(detail_kind=CODEX_ABUSE_POLICY_KIND),
                detail=CodexAbusePolicyDetail(),
            ),
            CodexProductionPolicyEnvelope(
                header=CodexProductionPolicyHeader(detail_kind=CODEX_RETENTION_POLICY_KIND),
                detail=CodexRetentionPolicyDetail(),
            ),
            CodexProductionPolicyEnvelope(
                header=CodexProductionPolicyHeader(detail_kind=CODEX_SLO_POLICY_KIND),
                detail=CodexSloPolicyDetail(rollout_stage=CodexCanaryStage.INVITED),
            ),
        )

        restored = tuple(
            CodexProductionPolicyEnvelope.model_validate_json(policy.model_dump_json())
            for policy in policies
        )

        assert isinstance(restored[0].detail, CodexAbusePolicyDetail)
        assert isinstance(restored[1].detail, CodexRetentionPolicyDetail)
        assert restored[1].detail.agent_command_journal_seconds == DAYS_PER_WEEK * SECONDS_PER_DAY
        assert isinstance(restored[2].detail, CodexSloPolicyDetail)
        assert restored[2].detail.rollout_stage is CodexCanaryStage.INVITED

    def test_policy_should_reject_mismatched_header_and_out_of_range_thresholds(self) -> None:
        with pytest.raises(ValidationError, match="detail_kind"):
            CodexProductionPolicyEnvelope(
                header=CodexProductionPolicyHeader(detail_kind=CODEX_ABUSE_POLICY_KIND),
                detail=CodexSloPolicyDetail(),
            )
        with pytest.raises(ValidationError):
            CodexAbusePolicyDetail(enrollment_per_ip_per_hour=0)
        with pytest.raises(ValidationError):
            CodexRetentionPolicyDetail(completed_outbox_seconds=1)
        with pytest.raises(ValidationError):
            CodexSloPolicyDetail(error_budget_percent=0)
