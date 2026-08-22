"""Codex 体验开关发布治理单元测试。"""

from __future__ import annotations

from src.core.codex_contract.feature_flags_contract import (
    CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES,
    CodexExperienceFeatureFlagDeletionCondition,
    CodexExperienceFeatureFlagFallbackPath,
    CodexExperienceFeatureFlagName,
    CodexExperienceFeatureFlags,
)


def test_feature_flag_decisions_should_keep_defaults_fallbacks_and_deletion_conditions() -> None:
    """默认关闭的开关必须生成完整、固定的发布治理决策。"""

    decisions = CodexExperienceFeatureFlags().decisions()

    assert tuple(policy.default_enabled for policy in CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES) == (
        False,
        False,
        False,
    )
    assert tuple(decision.name for decision in decisions) == (
        CodexExperienceFeatureFlagName.SCROLL_CONTROLLER_V2,
        CodexExperienceFeatureFlagName.REALTIME_BATCH_V2,
        CodexExperienceFeatureFlagName.AUTHORITY_RECOVERY_V2,
    )
    assert tuple(decision.enabled for decision in decisions) == (False, False, False)
    assert tuple(decision.fallback_path for decision in decisions) == (
        CodexExperienceFeatureFlagFallbackPath.LEGACY_TIMELINE_SCROLL,
        CodexExperienceFeatureFlagFallbackPath.LEGACY_REALTIME_EVENT_STREAM,
        CodexExperienceFeatureFlagFallbackPath.LEGACY_AUTHORITY_REFRESH,
    )
    assert tuple(decision.deletion_condition for decision in decisions) == (
        CodexExperienceFeatureFlagDeletionCondition.SCROLL_RELEASE_CYCLE_VERIFIED,
        CodexExperienceFeatureFlagDeletionCondition.REALTIME_BATCH_RELEASE_CYCLE_VERIFIED,
        CodexExperienceFeatureFlagDeletionCondition.AUTHORITY_RECOVERY_RELEASE_CYCLE_VERIFIED,
    )


def test_feature_flag_decisions_should_reflect_only_current_server_values() -> None:
    """策略元数据固定时，仅当前服务端批准值可以改变决策快照。"""

    decisions = CodexExperienceFeatureFlags(
        codex_scroll_controller_v2=True,
        codex_realtime_batch_v2=False,
        codex_authority_recovery_v2=True,
    ).decisions()

    assert tuple(decision.enabled for decision in decisions) == (True, False, True)
    assert all(decision.default_enabled is False for decision in decisions)
