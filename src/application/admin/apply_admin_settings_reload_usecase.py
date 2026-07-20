"""
管理员配置热更新执行用例。
"""

from __future__ import annotations

from src.application.ports.admin_settings_reload_port import (
    AdminSettingsReloadPort,
    AdminSettingsReloadResultSnapshot,
)


class ApplyAdminSettingsReloadUsecase:
    """
    管理员配置热更新执行用例。
    """

    def __init__(
        self,
        *,
        admin_settings_reload_port: AdminSettingsReloadPort,
    ) -> None:
        """
        初始化管理员配置热更新执行用例。

        :param admin_settings_reload_port: 管理员配置热更新端口。
        :type admin_settings_reload_port: AdminSettingsReloadPort
        :returns: 无返回值。
        :rtype: None
        """

        self._admin_settings_reload_port = admin_settings_reload_port

    def execute(self) -> AdminSettingsReloadResultSnapshot:
        """
        执行当前环境的配置热更新。

        :returns: 配置热更新结果。
        :rtype: AdminSettingsReloadResultSnapshot
        """

        return self._admin_settings_reload_port.apply_admin_settings_reload()
