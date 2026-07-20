"""
管理员配置热更新基础设施适配器。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.ports.admin_settings_reload_port import (
    AdminSettingsReloadCandidateSnapshot,
    AdminSettingsReloadResultSnapshot,
)
from src.infrastructure.settings.settings_reload_coordinator import (
    ReloadCandidatePayload,
    ReloadResultPayload,
    SettingsReloadCoordinator,
)

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount


class AdminSettingsReloadAdapter:
    """
    管理员配置热更新适配器。
    """

    def __init__(
        self,
        *,
        resource_mount: SharedResourceMount,
        reload_coordinator: SettingsReloadCoordinator,
    ) -> None:
        """
        初始化管理员配置热更新适配器。

        :param resource_mount: 共享资源挂载点。
        :type resource_mount: SharedResourceMount
        :param reload_coordinator: 配置热更新协调器。
        :type reload_coordinator: SettingsReloadCoordinator
        :returns: 无返回值。
        :rtype: None
        """

        self._resource_mount = resource_mount
        self._reload_coordinator = reload_coordinator

    def build_admin_settings_reload_candidate(
        self,
    ) -> AdminSettingsReloadCandidateSnapshot:
        """
        构建当前环境的配置热更新候选。

        :returns: 管理员配置热更新候选快照。
        :rtype: AdminSettingsReloadCandidateSnapshot
        """

        return self._build_candidate_snapshot(
            self._reload_coordinator.build_candidate(
                self._resource_mount.read_runtime_bundle().settings.app.environment
            )
        )

    def apply_admin_settings_reload(self) -> AdminSettingsReloadResultSnapshot:
        """
        执行当前环境的配置热更新。

        :returns: 管理员配置热更新结果快照。
        :rtype: AdminSettingsReloadResultSnapshot
        """

        return self._build_result_snapshot(
            self._reload_coordinator.reload(
                self._resource_mount.read_runtime_bundle().settings.app.environment
            )
        )

    def _build_candidate_snapshot(
        self,
        candidate: ReloadCandidatePayload,
    ) -> AdminSettingsReloadCandidateSnapshot:
        """
        构建候选快照。

        :param candidate: 配置热更新候选载荷。
        :type candidate: ReloadCandidatePayload
        :returns: 管理员配置热更新候选快照。
        :rtype: AdminSettingsReloadCandidateSnapshot
        """

        return AdminSettingsReloadCandidateSnapshot(
            candidate_version=candidate.candidate_version,
            digest=candidate.digest,
        )

    def _build_result_snapshot(
        self,
        result: ReloadResultPayload,
    ) -> AdminSettingsReloadResultSnapshot:
        """
        构建结果快照。

        :param result: 配置热更新结果载荷。
        :type result: ReloadResultPayload
        :returns: 管理员配置热更新结果快照。
        :rtype: AdminSettingsReloadResultSnapshot
        """

        return AdminSettingsReloadResultSnapshot(
            success=result.success,
            rolled_back=result.rolled_back,
            reason=result.reason,
            candidate_version=result.candidate_version,
            restored_resources=list(result.restored_resources),
            active_snapshot_id=result.active_snapshot_id,
        )
