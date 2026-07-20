"""
IP 封禁守卫模块。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from logging import Logger, getLogger

from fastapi import Request
from pydantic import ValidationError

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockRequest,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork
from src.core.security_contract.security_ip_block_contract import (
    IpBlockCacheEntry,
    SecurityIpBlockReason,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.concurrency.distributed_lock_provider import DistributedLockProvider
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from src.infrastructure.persistence.repository_impl.security_ip_block_repository import (
    SecurityIpBlockRepository,
)
from src.infrastructure.security.client_ip_resolver import ClientIpResolver

IP_BLOCK_CACHE_SEGMENT = "active"
IP_BLOCK_LOCK_NAMESPACE = "ip_block"
IP_BLOCK_LOCK_WAIT_SECONDS = 0
IP_BLOCK_DENIED_MESSAGE = "当前 IP 已被封禁。"
IP_BLOCK_CACHE_UNAVAILABLE_MESSAGE = "IP 封禁缓存不可用。"
IP_BLOCK_REMAINING_SECONDS_MINIMUM = 1
IP_BLOCK_CACHE_PARSE_WARNING = "IP 封禁缓存值解析失败，已回退查询数据库。"


@dataclass(slots=True)
class IpBlockResult:
    """
    IP 封禁结果。
    """

    blocked: bool
    ip_digest: str
    retry_after_seconds: int | None
    reason: SecurityIpBlockReason | None = None
    blocked_until_epoch: int | None = None


class IpBlockGuard:
    """
    IP 封禁守卫。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        digest_service: SensitiveDigestService,
        lock_provider: DistributedLockProvider,
        unit_of_work_factory: Callable[[], UnitOfWork],
        repository_factory: Callable[[PersistenceSession], SecurityIpBlockRepository],
        client_ip_resolver: ClientIpResolver | None = None,
        timer: Callable[[], float] | None = None,
        logger: Logger | None = None,
    ) -> None:
        """
        初始化 IP 封禁守卫。
        """

        self._cache_store = cache_store
        self._key_builder = key_builder
        self._digest_service = digest_service
        self._lock_provider = lock_provider
        self._unit_of_work_factory = unit_of_work_factory
        self._repository_factory = repository_factory
        self._client_ip_resolver = client_ip_resolver or ClientIpResolver()
        self._timer = timer or time.time
        self._logger = logger or getLogger(__name__)

    def evaluate(self, request: Request, *, cache_ttl_seconds: int) -> IpBlockResult:
        """
        评估请求 IP 是否被封禁。
        """

        ip_digest = self._digest_service.digest(self._client_ip_resolver.resolve_client_ip(request))
        cache_key = self._build_cache_key(ip_digest)
        try:
            cached_value = self._cache_store.get_value(cache_key)
        except Exception as exc:
            raise self._build_cache_fault(exc) from exc
        if cached_value is not None:
            current_epoch = int(self._timer())
            cached_entry = self._parse_cache_entry(cached_value)
            if cached_entry is not None:
                retry_after_seconds = self._calculate_retry_after_seconds(
                    blocked_until_epoch=cached_entry.blocked_until_epoch,
                    current_epoch=current_epoch,
                )
                if retry_after_seconds > 0:
                    return IpBlockResult(
                        blocked=True,
                        ip_digest=ip_digest,
                        retry_after_seconds=retry_after_seconds,
                        reason=cached_entry.reason,
                        blocked_until_epoch=cached_entry.blocked_until_epoch,
                    )
                self._delete_cache_entry(cache_key)
            else:
                self._logger.warning(IP_BLOCK_CACHE_PARSE_WARNING)
                self._delete_cache_entry(cache_key)
        unit_of_work = self._unit_of_work_factory()
        try:
            session = unit_of_work.get_session()
            repository = self._repository_factory(session)
            current_epoch = int(self._timer())
            active_record = repository.get_active_by_ip_digest(
                ip_digest,
                current_epoch=current_epoch,
            )
            if active_record is None:
                return IpBlockResult(False, ip_digest, None)
            retry_after_seconds = self._calculate_retry_after_seconds(
                blocked_until_epoch=active_record.blocked_until_epoch,
                current_epoch=current_epoch,
            )
            effective_ttl_seconds = self._calculate_cache_ttl_seconds(
                blocked_until_epoch=active_record.blocked_until_epoch,
                current_epoch=current_epoch,
                cache_ttl_seconds=cache_ttl_seconds,
            )
            self._cache_store.set_value(
                cache_key,
                self._build_cache_entry_json(
                    blocked_until_epoch=active_record.blocked_until_epoch,
                    reason=active_record.reason,
                ),
                effective_ttl_seconds,
            )
            return IpBlockResult(
                blocked=True,
                ip_digest=ip_digest,
                retry_after_seconds=retry_after_seconds,
                reason=SecurityIpBlockReason(active_record.reason),
                blocked_until_epoch=active_record.blocked_until_epoch,
            )
        finally:
            unit_of_work.dispose()

    def block_ip(
        self,
        *,
        ip_digest: str,
        reason: SecurityIpBlockReason,
        block_seconds: int,
        cache_ttl_seconds: int,
    ) -> None:
        """
        在分布式锁保护下写入 IP 封禁记录。
        """

        lock_request = DistributedLockRequest(
            namespace=IP_BLOCK_LOCK_NAMESPACE,
            key_digest=ip_digest,
            owner=str(uuid.uuid4()),
            lease_seconds=cache_ttl_seconds,
            wait_seconds=IP_BLOCK_LOCK_WAIT_SECONDS,
        )
        lease = self._lock_provider.acquire(lock_request)
        unit_of_work = self._unit_of_work_factory()
        try:
            session = unit_of_work.get_session()
            repository = self._repository_factory(session)
            current_epoch = int(self._timer())
            blocked_until_epoch = current_epoch + block_seconds
            active_record = repository.get_active_by_ip_digest(
                ip_digest,
                current_epoch=current_epoch,
            )
            if active_record is None:
                repository.create_block_record(
                    ip_digest=ip_digest,
                    reason=reason,
                    blocked_until_epoch=blocked_until_epoch,
                )
                unit_of_work.commit()
            else:
                blocked_until_epoch = active_record.blocked_until_epoch
            effective_ttl_seconds = self._calculate_cache_ttl_seconds(
                blocked_until_epoch=blocked_until_epoch,
                current_epoch=current_epoch,
                cache_ttl_seconds=cache_ttl_seconds,
            )
            self._cache_store.set_value(
                self._build_cache_key(ip_digest),
                self._build_cache_entry_json(
                    blocked_until_epoch=blocked_until_epoch,
                    reason=reason,
                ),
                effective_ttl_seconds,
            )
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
            self._lock_provider.release(lease)

    def release_ip(self, *, ip_digest: str, released_reason: str) -> bool:
        """
        释放 IP 封禁并清理缓存。
        """

        unit_of_work = self._unit_of_work_factory()
        committed = False
        try:
            session = unit_of_work.get_session()
            repository = self._repository_factory(session)
            released_count = repository.release_active_by_ip_digest(
                ip_digest=ip_digest,
                released_reason=released_reason,
            )
            unit_of_work.commit()
            committed = True
            try:
                self._cache_store.delete_value(self._build_cache_key(ip_digest))
            except Exception as exc:
                raise self._build_cache_fault(exc) from exc
            return released_count > 0
        except Exception:
            if not committed:
                unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _calculate_cache_ttl_seconds(
        self,
        *,
        blocked_until_epoch: int,
        current_epoch: int,
        cache_ttl_seconds: int,
    ) -> int:
        """
        计算不超过数据库封禁有效期的缓存 TTL。
        """

        remaining_seconds = max(
            IP_BLOCK_REMAINING_SECONDS_MINIMUM,
            blocked_until_epoch - current_epoch,
        )
        return min(cache_ttl_seconds, remaining_seconds)

    def _calculate_retry_after_seconds(
        self,
        *,
        blocked_until_epoch: int,
        current_epoch: int,
    ) -> int:
        """
        计算真实剩余封禁秒数。
        """

        return max(0, blocked_until_epoch - current_epoch)

    def _build_cache_entry_json(
        self,
        *,
        blocked_until_epoch: int,
        reason: SecurityIpBlockReason | str,
    ) -> str:
        """
        构建 IP 封禁缓存项 JSON。
        """

        return IpBlockCacheEntry(
            blocked_until_epoch=blocked_until_epoch,
            reason=SecurityIpBlockReason(reason),
        ).model_dump_json()

    def _parse_cache_entry(self, cached_value: str) -> IpBlockCacheEntry | None:
        """
        解析 IP 封禁缓存项。
        """

        try:
            return IpBlockCacheEntry.model_validate_json(cached_value)
        except (TypeError, ValidationError):
            return None

    def _delete_cache_entry(self, cache_key: str) -> None:
        """
        删除 IP 封禁缓存项。
        """

        try:
            self._cache_store.delete_value(cache_key)
        except Exception as exc:
            raise self._build_cache_fault(exc) from exc

    def _build_cache_key(self, ip_digest: str) -> str:
        """
        构建 IP 封禁缓存键。
        """

        return self._key_builder.build(
            namespace=CacheNamespace.IP_BLOCK,
            key_parts=[IP_BLOCK_CACHE_SEGMENT, ip_digest],
        )

    def _build_cache_fault(self, exc: Exception) -> HttpFaultException:
        """
        构建缓存不可用异常。
        """

        return HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CACHE_UNAVAILABLE,
            message=IP_BLOCK_CACHE_UNAVAILABLE_MESSAGE,
            detail=str(exc),
        )
