"""
管理员日志记录查询用例。
"""

from __future__ import annotations

from src.application.ports.admin_log_query_port import (
    AdminLogQueryPort,
    AdminLogRecordFilter,
    AdminLogRecordSnapshot,
)


class ListAdminLogRecordsUsecase:
    """
    管理员日志记录查询用例。
    """

    def __init__(self, *, admin_log_query_port: AdminLogQueryPort) -> None:
        """
        初始化管理员日志记录查询用例。

        :param admin_log_query_port: 管理员日志查询端口。
        :type admin_log_query_port: AdminLogQueryPort
        :returns: 无返回值。
        :rtype: None
        """

        self._admin_log_query_port = admin_log_query_port

    def execute(
        self,
        query_filter: AdminLogRecordFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        执行管理员日志记录查询。

        :param query_filter: 日志记录过滤条件。
        :type query_filter: AdminLogRecordFilter
        :returns: 日志记录快照列表。
        :rtype: list[AdminLogRecordSnapshot]
        """

        return self._admin_log_query_port.list_admin_log_records(query_filter)
