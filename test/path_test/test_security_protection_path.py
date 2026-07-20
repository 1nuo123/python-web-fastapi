"""
安全防护路径测试模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from src.core.security_contract.security_decision_contract import SecurityAction
from src.core.security_contract.security_event_contract import SecurityEventType
from src.core.security_contract.security_ip_block_contract import SecurityIpBlockReason
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import DistributedLockProvider
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from src.infrastructure.security.ip_block_guard import IpBlockGuard
from src.infrastructure.security.rate_limit_guard import RateLimitGuard
from src.infrastructure.security.security_protection_guard import SecurityProtectionGuard


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

    def get_session(self) -> object:
        """
        获取测试会话。
        """

        return object()

    def commit(self) -> None:
        """
        提交测试事务。
        """

    def rollback(self) -> None:
        """
        回滚测试事务。
        """

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


class TestSecurityProtectionPath:
    """
    安全防护路径测试集合。
    """

    def test_rate_limit_exceeded_should_return_429_decision(self) -> None:
        """
        验证超过限流阈值时返回 429 决策。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="path")
        digest_service = SensitiveDigestService(salt="path-test-secret")
        repository = FakeSecurityIpBlockRepository()
        guard = SecurityProtectionGuard(
            ip_block_guard=IpBlockGuard(
                cache_store=cache_store,
                key_builder=key_builder,
                digest_service=digest_service,
                lock_provider=DistributedLockProvider(
                    cache_store=cache_store,
                    key_builder=key_builder,
                ),
                unit_of_work_factory=FakeUnitOfWork,
                repository_factory=lambda _session: repository,
                timer=lambda: 1000.0,
            ),
            rate_limit_guard=RateLimitGuard(
                cache_store=cache_store,
                key_builder=key_builder,
                digest_service=digest_service,
            ),
        )
        request = self._build_request()
        guard.evaluate_request(
            request=request,
            limit=1,
            window_seconds=60,
            block_seconds=60,
            ip_block_cache_ttl_seconds=60,
        )

        decision = guard.evaluate_request(
            request=request,
            limit=1,
            window_seconds=60,
            block_seconds=60,
            ip_block_cache_ttl_seconds=60,
        )
        blocked_decision = guard.evaluate_request(
            request=request,
            limit=1,
            window_seconds=60,
            block_seconds=60,
            ip_block_cache_ttl_seconds=60,
        )

        assert decision.action == SecurityAction.RETURN_429
        assert decision.security_event is not None
        assert decision.security_event.header.event_type == SecurityEventType.RATE_LIMIT_BLOCKED
        assert blocked_decision.action == SecurityAction.RETURN_429
        assert blocked_decision.security_event is not None
        assert blocked_decision.security_event.header.event_type == SecurityEventType.IP_BLOCKED
        assert blocked_decision.security_event.detail.blocked is True
        cache_store.close()

    def _build_request(self) -> Request:
        """
        构建请求。
        """

        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
