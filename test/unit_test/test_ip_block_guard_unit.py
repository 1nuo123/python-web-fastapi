"""
IP 封禁守卫单元测试模块。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from starlette.requests import Request

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.security_contract.security_ip_block_contract import (
    IpBlockCacheEntry,
    SecurityIpBlockReason,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import DistributedLockProvider
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from src.infrastructure.security.client_ip_resolver import (
    ClientIpResolutionKind,
    ClientIpResolver,
)
from src.infrastructure.security.ip_block_guard import IpBlockGuard

CACHE_DELETE_FAILURE_MESSAGE = "缓存删除失败"
RELEASE_REASON = "人工解除"
INITIAL_EPOCH_SECONDS = 1000.0
LONG_CACHE_TTL_SECONDS = 60
SHORT_BLOCK_SECONDS = 10
EXPIRED_EPOCH_ADVANCE_SECONDS = 11
DIRECT_CLIENT_IP = "198.51.100.10"
TRUSTED_PROXY_IP = "127.0.0.1"
FORWARDED_CLIENT_IP = "203.0.113.10"
UNTRUSTED_PROXY_IP = "198.51.100.20"
FORWARDED_HEADER = "forwarded"
FORWARDED_HEADER_VALUE = f"for={FORWARDED_CLIENT_IP};proto=https"
X_FORWARDED_FOR_HEADER = "x-forwarded-for"


@dataclass(slots=True)
class FakeBlockRecord:
    """
    测试封禁记录。
    """

    ip_digest: str
    reason: SecurityIpBlockReason
    blocked_until_epoch: int


class FakeUnitOfWork:
    """
    测试工作单元。
    """

    def __init__(self) -> None:
        """
        初始化测试工作单元。
        """

        self.committed = False
        self.rolled_back = False

    def get_session(self) -> object:
        """
        获取测试会话。
        """

        return object()

    def commit(self) -> None:
        """
        提交测试事务。
        """

        self.committed = True

    def rollback(self) -> None:
        """
        回滚测试事务。
        """

        self.rolled_back = True

    def dispose(self) -> None:
        """
        释放测试事务。
        """


class FakeSecurityIpBlockRepository:
    """
    测试封禁仓储。
    """

    def __init__(self) -> None:
        """
        初始化测试仓储。
        """

        self.records: list[FakeBlockRecord] = []

    def get_active_by_ip_digest(
        self,
        ip_digest: str,
        *,
        current_epoch: int,
    ) -> FakeBlockRecord | None:
        """
        获取有效封禁记录。
        """

        for record in self.records:
            if record.ip_digest == ip_digest and record.blocked_until_epoch > current_epoch:
                return record
        return None

    def create_block_record(
        self,
        *,
        ip_digest: str,
        reason: SecurityIpBlockReason,
        blocked_until_epoch: int,
    ) -> FakeBlockRecord:
        """
        创建封禁记录。
        """

        record = FakeBlockRecord(
            ip_digest=ip_digest,
            reason=reason,
            blocked_until_epoch=blocked_until_epoch,
        )
        self.records.append(record)
        return record

    def release_active_by_ip_digest(
        self,
        *,
        ip_digest: str,
        released_reason: str,
    ) -> int:
        """
        释放封禁记录。
        """

        original_count = len(self.records)
        self.records = [record for record in self.records if record.ip_digest != ip_digest]
        return original_count - len(self.records)


@dataclass(slots=True)
class ManualClock:
    """
    测试时钟。
    """

    current_time: float

    def now(self) -> float:
        """
        读取当前时间。
        """

        return self.current_time

    def advance(self, seconds: int) -> None:
        """
        推进当前时间。
        """

        self.current_time += seconds


class FailingDeleteCacheStore(MemoryCacheStore):
    """
    删除失败的测试缓存。
    """

    def delete_value(self, key: str) -> None:
        """
        模拟缓存删除失败。
        """

        _ = key
        raise RuntimeError(CACHE_DELETE_FAILURE_MESSAGE)


class TestIpBlockGuardUnit:
    """
    IP 封禁守卫单元测试集合。
    """

    def test_block_ip_should_create_single_active_record_and_cache(self) -> None:
        """
        验证封禁写库后可通过缓存命中。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="unit")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=FakeUnitOfWork,
            repository_factory=lambda _session: repository,
            timer=lambda: 1000.0,
        )
        request = self._build_request()
        ip_digest = guard.evaluate(request, cache_ttl_seconds=60).ip_digest

        guard.block_ip(
            ip_digest=ip_digest,
            reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            block_seconds=60,
            cache_ttl_seconds=60,
        )
        guard.block_ip(
            ip_digest=ip_digest,
            reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            block_seconds=60,
            cache_ttl_seconds=60,
        )
        result = guard.evaluate(request, cache_ttl_seconds=60)

        assert len(repository.records) == 1
        assert result.blocked is True
        cache_store.close()

    def test_block_ip_cache_ttl_should_not_exceed_block_seconds(self) -> None:
        """
        验证主动封禁写缓存时 TTL 不超过数据库封禁有效期。
        """

        clock = ManualClock(current_time=INITIAL_EPOCH_SECONDS)
        cache_store = MemoryCacheStore(timer=clock.now)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=FakeUnitOfWork,
            repository_factory=lambda _session: repository,
            timer=clock.now,
        )
        request = self._build_request()
        ip_digest = guard.evaluate(request, cache_ttl_seconds=LONG_CACHE_TTL_SECONDS).ip_digest

        guard.block_ip(
            ip_digest=ip_digest,
            reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            block_seconds=SHORT_BLOCK_SECONDS,
            cache_ttl_seconds=LONG_CACHE_TTL_SECONDS,
        )
        blocked_result = guard.evaluate(
            request,
            cache_ttl_seconds=LONG_CACHE_TTL_SECONDS,
        )
        clock.advance(EXPIRED_EPOCH_ADVANCE_SECONDS)
        expired_result = guard.evaluate(
            request,
            cache_ttl_seconds=LONG_CACHE_TTL_SECONDS,
        )

        assert blocked_result.blocked is True
        assert blocked_result.retry_after_seconds == SHORT_BLOCK_SECONDS
        assert expired_result.blocked is False
        cache_store.close()

    def test_db_backfill_ttl_should_not_exceed_record_expiry_and_release_deletes_cache(
        self,
    ) -> None:
        """
        验证数据库回填 TTL 不超过封禁有效期，释放后同步删除缓存。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="unit")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=FakeUnitOfWork,
            repository_factory=lambda _session: repository,
            timer=lambda: 1000.0,
        )
        request = self._build_request()
        ip_digest = guard.evaluate(request, cache_ttl_seconds=60).ip_digest
        repository.create_block_record(
            ip_digest=ip_digest,
            reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            blocked_until_epoch=1030,
        )

        backfilled_result = guard.evaluate(request, cache_ttl_seconds=60)
        released = guard.release_ip(ip_digest=ip_digest, released_reason="人工解除")
        released_result = guard.evaluate(request, cache_ttl_seconds=60)

        assert backfilled_result.blocked is True
        assert backfilled_result.retry_after_seconds == 30
        assert released is True
        assert released_result.blocked is False
        cache_store.close()

    def test_cache_hit_retry_after_should_use_blocked_until_epoch(self) -> None:
        """
        验证缓存命中时 Retry-After 依据真实封禁结束时间计算。
        """

        clock = ManualClock(current_time=INITIAL_EPOCH_SECONDS)
        cache_store = MemoryCacheStore(timer=clock.now)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=FakeUnitOfWork,
            repository_factory=lambda _session: repository,
            timer=clock.now,
        )
        request = self._build_request()
        ip_digest = guard.evaluate(request, cache_ttl_seconds=LONG_CACHE_TTL_SECONDS).ip_digest

        cache_store.set_value(
            key_builder.build(
                namespace=CacheNamespace.IP_BLOCK,
                key_parts=["active", ip_digest],
            ),
            IpBlockCacheEntry(
                blocked_until_epoch=int(INITIAL_EPOCH_SECONDS) + SHORT_BLOCK_SECONDS,
                reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            ).model_dump_json(),
            LONG_CACHE_TTL_SECONDS,
        )
        result = guard.evaluate(
            request,
            cache_ttl_seconds=LONG_CACHE_TTL_SECONDS,
        )

        assert result.blocked is True
        assert result.retry_after_seconds == SHORT_BLOCK_SECONDS
        assert result.blocked_until_epoch == int(INITIAL_EPOCH_SECONDS) + SHORT_BLOCK_SECONDS
        cache_store.close()

    def test_release_when_no_active_record_should_return_false(self) -> None:
        """
        验证释放不存在的 IP 封禁记录时应返回未释放。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="unit")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=FakeUnitOfWork,
            repository_factory=lambda _session: repository,
            timer=lambda: 1000.0,
        )

        released = guard.release_ip(
            ip_digest="1234567890abcdef",
            released_reason=RELEASE_REASON,
        )

        assert released is False
        cache_store.close()

    def test_release_when_cache_delete_failed_should_keep_database_release_committed(
        self,
    ) -> None:
        """
        验证释放封禁时应先提交数据库变更再清理缓存。
        """

        cache_store = FailingDeleteCacheStore()
        lock_cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="unit")
        repository = FakeSecurityIpBlockRepository()
        repository.create_block_record(
            ip_digest="1234567890abcdef",
            reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            blocked_until_epoch=1300,
        )
        unit_of_work = FakeUnitOfWork()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=lock_cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=lambda: unit_of_work,
            repository_factory=lambda _session: repository,
            timer=lambda: 1000.0,
        )

        with pytest.raises(HttpFaultException):
            guard.release_ip(
                ip_digest="1234567890abcdef",
                released_reason=RELEASE_REASON,
            )

        assert unit_of_work.committed is True
        assert unit_of_work.rolled_back is False
        assert repository.records == []
        lock_cache_store.close()
        cache_store.close()

    def test_client_ip_resolver_should_use_forwarded_for_trusted_proxy(
        self,
    ) -> None:
        """
        验证可信代理请求优先使用 Forwarded 客户端 IP。
        """

        resolver = ClientIpResolver()
        request = self._build_request(
            client_ip=TRUSTED_PROXY_IP,
            headers=[(FORWARDED_HEADER, FORWARDED_HEADER_VALUE)],
        )

        result = resolver.resolve(request)

        assert result.header.source == ClientIpResolutionKind.TRUSTED_PROXY_FORWARDED
        assert result.detail.client_ip == FORWARDED_CLIENT_IP

    def test_client_ip_resolver_should_ignore_forwarded_for_untrusted_proxy(
        self,
    ) -> None:
        """
        验证非可信代理请求不会信任转发头。
        """

        resolver = ClientIpResolver()
        request = self._build_request(
            client_ip=UNTRUSTED_PROXY_IP,
            headers=[(X_FORWARDED_FOR_HEADER, FORWARDED_CLIENT_IP)],
        )

        result = resolver.resolve(request)

        assert result.header.source == ClientIpResolutionKind.DIRECT
        assert result.detail.client_ip == UNTRUSTED_PROXY_IP

    def _build_request(
        self,
        *,
        client_ip: str = DIRECT_CLIENT_IP,
        headers: list[tuple[str, str]] | None = None,
    ) -> Request:
        """
        构建请求。
        """

        raw_headers = [
            (name.encode("latin-1"), value.encode("latin-1")) for name, value in (headers or [])
        ]
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": raw_headers,
                "client": (client_ip, 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
