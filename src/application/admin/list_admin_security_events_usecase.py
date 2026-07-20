"""
管理员安全事件查询用例。
"""

from __future__ import annotations

from src.application.ports.admin_log_query_port import (
    AdminLogQueryPort,
    AdminLogRecordSnapshot,
    AdminSecurityEventFilter,
)


class ListAdminSecurityEventsUsecase:
    """
    管理员安全事件查询用例。
    """

    def __init__(self, *, admin_log_query_port: AdminLogQueryPort) -> None:
        """
        初始化管理员安全事件查询用例。

        :param admin_log_query_port: 管理员日志查询端口。
        :type admin_log_query_port: AdminLogQueryPort
        :returns: 无返回值。
        :rtype: None
        """

        self._admin_log_query_port = admin_log_query_port

    def execute(
        self,
        query_filter: AdminSecurityEventFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        执行管理员安全事件查询。

        :param query_filter: 安全事件过滤条件。
        :type query_filter: AdminSecurityEventFilter
        :returns: 安全事件日志快照列表。
        :rtype: list[AdminLogRecordSnapshot]
        """

        return self._admin_log_query_port.list_admin_security_events(query_filter)
