"""
管理员安全 IP 封禁管理用例。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.core.http_contract.request_scope_contract import RequestScope
from src.core.security_contract.security_ip_block_contract import SecurityIpBlockReason

SECURITY_IP_BLOCK_RECORD_NOT_FOUND_MESSAGE = "IP 封禁记录不存在。"
SECURITY_IP_BLOCK_RETRY_AFTER_MINIMUM_SECONDS = 0


@dataclass(slots=True)
class SecurityIpBlockRecordSnapshot:
    """
    安全 IP 封禁记录快照。
    """

    record_id: str
    ip_digest: str
    reason: str
    status: str
    blocked_until_epoch: int
    released_reason: str | None


@dataclass(slots=True)
class SecurityIpBlockEventContext:
    """
    安全 IP 封禁事件上下文。
    """

    request_scope: RequestScope


@dataclass(slots=True)
class SecurityIpBlockListQuery:
    """
    安全 IP 封禁列表查询。
    """

    limit: int
    status: str | None
    ip_digest: str | None


@dataclass(slots=True)
class SecurityIpBlockCreateCommand:
    """
    安全 IP 封禁创建命令。
    """

    ip_digest: str
    reason: SecurityIpBlockReason
    block_seconds: int
    event_context: SecurityIpBlockEventContext


@dataclass(slots=True)
class SecurityIpBlockGetQuery:
    """
    安全 IP 封禁详情查询。
    """

    record_id: UUID


@dataclass(slots=True)
class SecurityIpBlockReleaseCommand:
    """
    安全 IP 封禁释放命令。
    """

    ip_digest: str
    released_reason: str
    event_context: SecurityIpBlockEventContext


@dataclass(slots=True)
class SecurityIpBlockReleaseResult:
    """
    安全 IP 封禁释放结果。
    """

    ip_digest: str
    released: bool


class AdminSecurityIpBlockRuntimePort(Protocol):
    """
    管理员安全 IP 封禁运行时端口。
    """

    def list_admin_security_ip_blocks(
        self,
        query: SecurityIpBlockListQuery,
    ) -> list[SecurityIpBlockRecordSnapshot]:
        """
        查询安全 IP 封禁记录。
        """

    def create_admin_security_ip_block(
        self,
        command: SecurityIpBlockCreateCommand,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        创建安全 IP 封禁记录。
        """

    def get_admin_security_ip_block(
        self,
        query: SecurityIpBlockGetQuery,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        查询安全 IP 封禁详情。
        """

    def release_admin_security_ip_block(
        self,
        command: SecurityIpBlockReleaseCommand,
    ) -> SecurityIpBlockReleaseResult:
        """
        释放安全 IP 封禁记录。
        """


class ListAdminSecurityIpBlocksUsecase:
    """
    管理员安全 IP 封禁列表用例。
    """

    def __init__(self, *, runtime_port: AdminSecurityIpBlockRuntimePort) -> None:
        """
        初始化管理员安全 IP 封禁列表用例。
        """

        self._runtime_port = runtime_port

    def execute(
        self,
        query: SecurityIpBlockListQuery,
    ) -> list[SecurityIpBlockRecordSnapshot]:
        """
        执行安全 IP 封禁列表查询。
        """

        return self._runtime_port.list_admin_security_ip_blocks(query)


class CreateAdminSecurityIpBlockUsecase:
    """
    管理员安全 IP 封禁创建用例。
    """

    def __init__(self, *, runtime_port: AdminSecurityIpBlockRuntimePort) -> None:
        """
        初始化管理员安全 IP 封禁创建用例。
        """

        self._runtime_port = runtime_port

    def execute(
        self,
        command: SecurityIpBlockCreateCommand,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        执行安全 IP 封禁创建。
        """

        return self._runtime_port.create_admin_security_ip_block(command)


class GetAdminSecurityIpBlockUsecase:
    """
    管理员安全 IP 封禁详情用例。
    """

    def __init__(self, *, runtime_port: AdminSecurityIpBlockRuntimePort) -> None:
        """
        初始化管理员安全 IP 封禁详情用例。
        """

        self._runtime_port = runtime_port

    def execute(
        self,
        query: SecurityIpBlockGetQuery,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        执行安全 IP 封禁详情查询。
        """

        return self._runtime_port.get_admin_security_ip_block(query)


class ReleaseAdminSecurityIpBlockUsecase:
    """
    管理员安全 IP 封禁释放用例。
    """

    def __init__(self, *, runtime_port: AdminSecurityIpBlockRuntimePort) -> None:
        """
        初始化管理员安全 IP 封禁释放用例。
        """

        self._runtime_port = runtime_port

    def execute(
        self,
        command: SecurityIpBlockReleaseCommand,
    ) -> SecurityIpBlockReleaseResult:
        """
        执行安全 IP 封禁释放。
        """

        return self._runtime_port.release_admin_security_ip_block(command)
