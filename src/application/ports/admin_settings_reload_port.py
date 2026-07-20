"""
管理员配置热更新应用端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AdminSettingsReloadCandidateSnapshot:
    """
    管理员配置热更新候选快照。
    """

    candidate_version: str
    digest: str


@dataclass(slots=True)
class AdminSettingsReloadResultSnapshot:
    """
    管理员配置热更新结果快照。
    """

    success: bool
    rolled_back: bool
    reason: str | None
    candidate_version: str | None
    restored_resources: list[str]
    active_snapshot_id: str | None


class AdminSettingsReloadPort(Protocol):
    """
    管理员配置热更新端口。
    """

    def build_admin_settings_reload_candidate(
        self,
    ) -> AdminSettingsReloadCandidateSnapshot:
        """
        构建当前环境的配置热更新候选。
        """

    def apply_admin_settings_reload(self) -> AdminSettingsReloadResultSnapshot:
        """
        执行当前环境的配置热更新。
        """
