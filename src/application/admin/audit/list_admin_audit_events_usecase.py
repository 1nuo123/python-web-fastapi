"""
业务后台审计事件列表查询用例。
"""

from __future__ import annotations

from src.application.ports.admin_audit_query_port import (
    AdminAuditEventPage,
    AdminAuditQuery,
    AdminAuditQueryPort,
)


class ListAdminAuditEventsUsecase:
    """
    业务后台审计事件列表查询用例。
    """

    def __init__(self, *, admin_audit_query_port: AdminAuditQueryPort) -> None:
        """
        初始化业务审计查询用例。

        :param admin_audit_query_port: 业务审计查询端口。
        :type admin_audit_query_port: AdminAuditQueryPort
        :returns: 无返回值。
        :rtype: None
        """

        self._admin_audit_query_port = admin_audit_query_port

    def execute(self, query: AdminAuditQuery) -> AdminAuditEventPage:
        """
        执行业务审计查询。

        :param query: 业务审计查询条件。
        :type query: AdminAuditQuery
        :returns: 业务审计分页结果。
        :rtype: AdminAuditEventPage
        """

        return self._admin_audit_query_port.list_admin_audit_events(query)
