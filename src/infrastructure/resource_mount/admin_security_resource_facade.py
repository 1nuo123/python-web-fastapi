"""管理员安全资源。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

import time
from http import HTTPStatus

from src.application.admin.security_protection.manage_admin_security_ip_blocks_usecase import (
    SECURITY_IP_BLOCK_RECORD_NOT_FOUND_MESSAGE,
    SECURITY_IP_BLOCK_RETRY_AFTER_MINIMUM_SECONDS,
    SecurityIpBlockCreateCommand,
    SecurityIpBlockGetQuery,
    SecurityIpBlockListQuery,
    SecurityIpBlockRecordSnapshot,
    SecurityIpBlockReleaseCommand,
    SecurityIpBlockReleaseResult,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.core.security_contract.security_event_contract import (
    SecurityEventType,
)
from src.infrastructure.persistence.orm_model.security_ip_block_record_orm_model import (
    SecurityIpBlockRecordOrmModel,
)
from src.infrastructure.persistence.repository_impl.security_ip_block_repository import (
    SecurityIpBlockRepository,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle


class AdminSecurityResourceFacade(SharedResourceLifecycle):
    """管理员安全资源门面。"""

    def create_security_ip_block_repository(
        self,
        session: PersistenceSession,
    ) -> SecurityIpBlockRepository:
        """
        创建安全 IP 封禁仓储。
        """

        return SecurityIpBlockRepository(self._read_sqlalchemy_session(session))

    def list_admin_security_ip_blocks(
        self,
        query: SecurityIpBlockListQuery,
    ) -> list[SecurityIpBlockRecordSnapshot]:
        """
        查询管理员安全 IP 封禁记录。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_security_ip_block_repository(unit_of_work.get_session())
            return [
                self._build_security_ip_block_snapshot(record)
                for record in repository.list_records(
                    limit=query.limit,
                    status=query.status,
                    ip_digest=query.ip_digest,
                )
            ]
        finally:
            unit_of_work.dispose()

    def create_admin_security_ip_block(
        self,
        command: SecurityIpBlockCreateCommand,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        创建管理员安全 IP 封禁记录。
        """

        security_settings = self.get_security_ip_block_runtime()
        self.get_ip_block_guard().block_ip(
            ip_digest=command.ip_digest,
            reason=command.reason,
            block_seconds=command.block_seconds,
            cache_ttl_seconds=security_settings.cache_ttl_seconds,
        )
        record = self._read_active_security_ip_block_record(ip_digest=command.ip_digest)
        self.emit_security_event(
            self.get_security_event_builder().build_ip_block_event_from_scope(
                request_scope=command.event_context.request_scope,
                ip_digest=command.ip_digest,
                reason_code=SecurityEventType.IP_BLOCKED.value,
                event_type=SecurityEventType.IP_BLOCKED,
                status_code=HTTPStatus.OK,
                blocked=True,
                blocked_until_epoch=record.blocked_until_epoch,
                retry_after_seconds=max(
                    SECURITY_IP_BLOCK_RETRY_AFTER_MINIMUM_SECONDS,
                    record.blocked_until_epoch - int(time.time()),
                ),
            )
        )
        return self._build_security_ip_block_snapshot(record)

    def get_admin_security_ip_block(
        self,
        query: SecurityIpBlockGetQuery,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        查询管理员安全 IP 封禁详情。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_security_ip_block_repository(unit_of_work.get_session())
            record = repository.get_by_record_id(query.record_id)
            if record is None:
                raise self._build_security_ip_block_not_found_fault(query.record_id)
            return self._build_security_ip_block_snapshot(record)
        finally:
            unit_of_work.dispose()

    def release_admin_security_ip_block(
        self,
        command: SecurityIpBlockReleaseCommand,
    ) -> SecurityIpBlockReleaseResult:
        """
        释放管理员安全 IP 封禁记录。
        """

        released = self.get_ip_block_guard().release_ip(
            ip_digest=command.ip_digest,
            released_reason=command.released_reason,
        )
        if released:
            self.emit_security_event(
                self.get_security_event_builder().build_ip_block_event_from_scope(
                    request_scope=command.event_context.request_scope,
                    ip_digest=command.ip_digest,
                    reason_code=SecurityEventType.IP_UNBLOCKED.value,
                    event_type=SecurityEventType.IP_UNBLOCKED,
                    status_code=HTTPStatus.OK,
                    blocked=False,
                    blocked_until_epoch=None,
                    retry_after_seconds=None,
                )
            )
        return SecurityIpBlockReleaseResult(
            ip_digest=command.ip_digest,
            released=released,
        )

    def _read_active_security_ip_block_record(
        self,
        *,
        ip_digest: str,
    ) -> SecurityIpBlockRecordOrmModel:
        """
        读取当前 IP 摘要的有效封禁记录。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_security_ip_block_repository(unit_of_work.get_session())
            record = repository.get_active_by_ip_digest(
                ip_digest,
                current_epoch=int(time.time()),
            )
            if record is None:
                raise self._build_security_ip_block_not_found_fault(ip_digest)
            return record
        finally:
            unit_of_work.dispose()

    def _build_security_ip_block_snapshot(
        self,
        record: SecurityIpBlockRecordOrmModel,
    ) -> SecurityIpBlockRecordSnapshot:
        """
        构建安全 IP 封禁记录快照。
        """

        return SecurityIpBlockRecordSnapshot(
            record_id=str(record.record_id),
            ip_digest=record.ip_digest,
            reason=record.reason,
            status=record.status,
            blocked_until_epoch=record.blocked_until_epoch,
            released_reason=record.released_reason,
        )

    def _build_security_ip_block_not_found_fault(
        self,
        record_key: object,
    ) -> HttpFaultException:
        """
        构建封禁记录不存在故障。
        """

        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CoreErrorCode.REQUEST_INVALID,
            message=SECURITY_IP_BLOCK_RECORD_NOT_FOUND_MESSAGE,
            detail=str(record_key),
        )
