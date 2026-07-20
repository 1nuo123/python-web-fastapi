"""
管理员配置热更新候选读取用例。
"""

from __future__ import annotations

from src.application.ports.admin_settings_reload_port import (
    AdminSettingsReloadCandidateSnapshot,
    AdminSettingsReloadPort,
)


class BuildAdminSettingsReloadCandidateUsecase:
    """
    管理员配置热更新候选读取用例。
    """

    def __init__(
        self,
        *,
        admin_settings_reload_port: AdminSettingsReloadPort,
    ) -> None:
        """
        初始化管理员配置热更新候选读取用例。
        """

        self._admin_settings_reload_port = admin_settings_reload_port

    def execute(self) -> AdminSettingsReloadCandidateSnapshot:
        """
        执行管理员配置热更新候选读取。
        """

        return self._admin_settings_reload_port.build_admin_settings_reload_candidate()
