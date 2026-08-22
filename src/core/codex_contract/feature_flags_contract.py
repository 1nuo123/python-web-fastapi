"""远程 Codex 体验优化功能开关契约。

开关策略与当前开关值在核心层保持封闭，避免 API 或前端各自维护默认值、回退路径
和删除条件。策略只描述发布治理元数据，不包含用户、会话或请求上下文。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict


class CodexExperienceFeatureFlagName(StrEnum):
    """远程 Codex 体验开关的稳定名称。"""

    SCROLL_CONTROLLER_V2 = "codex_scroll_controller_v2"
    REALTIME_BATCH_V2 = "codex_realtime_batch_v2"
    AUTHORITY_RECOVERY_V2 = "codex_authority_recovery_v2"


class CodexExperienceFeatureFlagFallbackPath(StrEnum):
    """开关关闭后可验证的旧实现路径。"""

    LEGACY_TIMELINE_SCROLL = "legacy_timeline_scroll"
    LEGACY_REALTIME_EVENT_STREAM = "legacy_realtime_event_stream"
    LEGACY_AUTHORITY_REFRESH = "legacy_authority_refresh"


class CodexExperienceFeatureFlagDeletionCondition(StrEnum):
    """删除新旧兼容路径前必须满足的发布验证条件。"""

    SCROLL_RELEASE_CYCLE_VERIFIED = (
        "android_chrome_desktop_scroll_release_cycle_and_legacy_fallback_rehearsal"
    )
    REALTIME_BATCH_RELEASE_CYCLE_VERIFIED = (
        "batch_loss_duplicate_epoch_release_cycle_and_client_server_fallback_rehearsal"
    )
    AUTHORITY_RECOVERY_RELEASE_CYCLE_VERIFIED = (
        "snapshot_cursor_gap_auth_expiry_disconnect_recovery_release_cycle"
    )


@dataclass(frozen=True, slots=True)
class CodexExperienceFeatureFlagPolicy:
    """单个开关的发布治理策略。

    :ivar name: 与 ``CodexExperienceFeatureFlags`` 字段一致的稳定名称。
    :ivar default_enabled: 新路径默认值，必须保持关闭以支持安全回退。
    :ivar fallback_path: 开关关闭时使用的旧路径。
    :ivar deletion_condition: 允许删除旧路径和开关的可验证条件。
    """

    name: CodexExperienceFeatureFlagName
    default_enabled: Literal[False]
    fallback_path: CodexExperienceFeatureFlagFallbackPath
    deletion_condition: CodexExperienceFeatureFlagDeletionCondition


CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES: Final[tuple[CodexExperienceFeatureFlagPolicy, ...]] = (
    CodexExperienceFeatureFlagPolicy(
        name=CodexExperienceFeatureFlagName.SCROLL_CONTROLLER_V2,
        default_enabled=False,
        fallback_path=CodexExperienceFeatureFlagFallbackPath.LEGACY_TIMELINE_SCROLL,
        deletion_condition=(
            CodexExperienceFeatureFlagDeletionCondition.SCROLL_RELEASE_CYCLE_VERIFIED
        ),
    ),
    CodexExperienceFeatureFlagPolicy(
        name=CodexExperienceFeatureFlagName.REALTIME_BATCH_V2,
        default_enabled=False,
        fallback_path=(CodexExperienceFeatureFlagFallbackPath.LEGACY_REALTIME_EVENT_STREAM),
        deletion_condition=(
            CodexExperienceFeatureFlagDeletionCondition.REALTIME_BATCH_RELEASE_CYCLE_VERIFIED
        ),
    ),
    CodexExperienceFeatureFlagPolicy(
        name=CodexExperienceFeatureFlagName.AUTHORITY_RECOVERY_V2,
        default_enabled=False,
        fallback_path=CodexExperienceFeatureFlagFallbackPath.LEGACY_AUTHORITY_REFRESH,
        deletion_condition=(
            CodexExperienceFeatureFlagDeletionCondition.AUTHORITY_RECOVERY_RELEASE_CYCLE_VERIFIED
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CodexExperienceFeatureFlagDecision:
    """一次服务端开关决策的低基数、无用户数据快照。"""

    name: CodexExperienceFeatureFlagName
    enabled: bool
    default_enabled: Literal[False]
    fallback_path: CodexExperienceFeatureFlagFallbackPath
    deletion_condition: CodexExperienceFeatureFlagDeletionCondition


class CodexExperienceFeatureFlags(BaseModel):
    """新路径开关，默认关闭以保留可回退的旧运行路径。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_scroll_controller_v2: bool = False
    codex_realtime_batch_v2: bool = False
    codex_authority_recovery_v2: bool = False

    def decisions(self) -> tuple[CodexExperienceFeatureFlagDecision, ...]:
        """将当前值与固定发布策略合并为可记录的决策快照。"""

        return tuple(
            CodexExperienceFeatureFlagDecision(
                name=policy.name,
                enabled=self._read_enabled_value(policy.name),
                default_enabled=policy.default_enabled,
                fallback_path=policy.fallback_path,
                deletion_condition=policy.deletion_condition,
            )
            for policy in CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES
        )

    def _read_enabled_value(self, name: CodexExperienceFeatureFlagName) -> bool:
        """按封闭枚举读取值，避免运行时反射遗漏新增开关。"""

        match name:
            case CodexExperienceFeatureFlagName.SCROLL_CONTROLLER_V2:
                return self.codex_scroll_controller_v2
            case CodexExperienceFeatureFlagName.REALTIME_BATCH_V2:
                return self.codex_realtime_batch_v2
            case CodexExperienceFeatureFlagName.AUTHORITY_RECOVERY_V2:
                return self.codex_authority_recovery_v2
        raise ValueError("未知的Codex体验开关名称。")
