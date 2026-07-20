"""
安全 IP 封禁集成测试模块。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api.endpoint_security_protection.route_security_protection import (
    SECURITY_PROTECTION_IP_BLOCK_PATH,
    SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.core.security_contract.security_ip_block_contract import (
    SecurityIpBlockReason,
    SecurityIpBlockStatus,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import DistributedLockProvider
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from src.infrastructure.persistence.orm_model.security_ip_block_record_orm_model import (
    SecurityIpBlockRecordOrmModel,
)
from src.infrastructure.security.ip_block_guard import IP_BLOCK_CACHE_SEGMENT, IpBlockGuard
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_mapping_merger import SettingsMappingMerger
from test.redis_integration_support import (
    REDIS_INTEGRATION_MAX_CONNECTIONS,
    RedisIntegrationAvailability,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
    pytest.mark.redis,
]


AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
RECORD_FIELD = "record"
RECORDS_FIELD = "records"
RECORD_ID_FIELD = "record_id"
IP_DIGEST_FIELD = "ip_digest"
STATUS_FIELD = "status"
ACCESS_TOKEN_FIELD = "access_token"
KIND_FIELD = "kind"
REASON_FIELD = "reason"
BLOCK_SECONDS_FIELD = "block_seconds"
RELEASED_REASON_FIELD = "released_reason"
IP_BLOCK_CREATE_KIND = "security_ip_block_create"
IP_BLOCK_RELEASE_KIND = "security_ip_block_release"
REDIS_TEST_URL_ENV = "REDIS_TEST_URL"
REDIS_CACHE_URL = os.getenv(REDIS_TEST_URL_ENV, "redis://127.0.0.1:56379/0")
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 1
REDIS_IP_BLOCK_KEY_PREFIX_TEMPLATE = "fastapi_web_skeleton_test_ip_block_{suffix}"
MANUAL_BLOCK_SECONDS = 120
RELEASED_REASON = "集成测试释放"
REDIS_BACKFILL_CLIENT_IP = "203.0.113.50"
IP_BLOCK_CACHE_TTL_SECONDS = 60
INITIAL_EPOCH_SECONDS = 1000.0
SHORT_BLOCK_SECONDS = 10
EXPIRED_EPOCH_ADVANCE_SECONDS = 11
APPLICATION_LAYER_SHORT_BLOCK_SECONDS = 1
APPLICATION_LAYER_BLOCK_EXPIRE_ADVANCE_SECONDS = 2
APPLICATION_LAYER_EXPIRY_CLIENT_IP = "203.0.113.77"
SECURITY_PROTECTION_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.SECURITY_PROTECTION.value,
]


@dataclass(slots=True)
class FakeBlockRecord:
    """
    测试封禁记录。
    """

    ip_digest: str
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
            blocked_until_epoch=blocked_until_epoch,
        )
        self.records.append(record)
        return record


@dataclass(slots=True)
class ManualClock:
    """
    集成测试时钟。
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


class TestSecurityIpBlockIntegration:
    """
    安全 IP 封禁集成测试集合。
    """

    def test_ip_block_should_write_and_hit_cache(self) -> None:
        """
        验证 IP 封禁落库语义与缓存命中语义。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="integration")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="integration-test-secret"),
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
        result = guard.evaluate(request, cache_ttl_seconds=60)

        assert len(repository.records) == 1
        assert result.blocked is True
        cache_store.close()

    def test_ip_block_cache_should_expire_with_database_block_window(self) -> None:
        """
        验证主动封禁缓存不会超过数据库封禁窗口。
        """

        clock = ManualClock(current_time=INITIAL_EPOCH_SECONDS)
        cache_store = MemoryCacheStore(timer=clock.now)
        key_builder = CacheKeyBuilder(key_prefix="integration")
        repository = FakeSecurityIpBlockRepository()
        guard = IpBlockGuard(
            cache_store=cache_store,
            key_builder=key_builder,
            digest_service=SensitiveDigestService(salt="integration-test-secret"),
            lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            unit_of_work_factory=FakeUnitOfWork,
            repository_factory=lambda _session: repository,
            timer=clock.now,
        )
        request = self._build_request()
        ip_digest = guard.evaluate(
            request,
            cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
        ).ip_digest

        guard.block_ip(
            ip_digest=ip_digest,
            reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
            block_seconds=SHORT_BLOCK_SECONDS,
            cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
        )
        blocked_result = guard.evaluate(
            request,
            cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
        )
        clock.advance(EXPIRED_EPOCH_ADVANCE_SECONDS)
        expired_result = guard.evaluate(
            request,
            cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
        )

        assert blocked_result.blocked is True
        assert expired_result.blocked is False
        cache_store.close()

    def test_ip_block_application_cache_should_release_after_database_window(
        self,
    ) -> None:
        """
        验证真实应用仓储下缓存不会超过数据库封禁有效期。
        """

        app = self._create_security_protection_app()
        ip_digest: str | None = None

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            guard = resource_mount.get_ip_block_guard()
            clock = ManualClock(current_time=time.time())
            guard._timer = clock.now  # noqa: SLF001
            request = self._build_request(client_ip=APPLICATION_LAYER_EXPIRY_CLIENT_IP)
            try:
                ip_digest = guard.evaluate(
                    request,
                    cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
                ).ip_digest
                guard.block_ip(
                    ip_digest=ip_digest,
                    reason=SecurityIpBlockReason.MANUAL,
                    block_seconds=APPLICATION_LAYER_SHORT_BLOCK_SECONDS,
                    cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
                )
                blocked_result = guard.evaluate(
                    request,
                    cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
                )
                clock.advance(APPLICATION_LAYER_BLOCK_EXPIRE_ADVANCE_SECONDS)
                expired_result = guard.evaluate(
                    request,
                    cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
                )
            finally:
                if ip_digest is not None:
                    self._delete_ip_block_records(app=app, ip_digest=ip_digest)

        assert blocked_result.blocked is True
        assert expired_result.blocked is False

    def test_ip_block_admin_should_sync_redis_cache_and_database(
        self,
    ) -> None:
        """
        验证 Redis 缓存与真实数据库封禁记录在管理释放后保持一致。
        """

        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=REDIS_CACHE_URL,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        key_prefix = REDIS_IP_BLOCK_KEY_PREFIX_TEMPLATE.format(suffix=uuid4().hex)
        ip_digest = uuid4().hex
        app = self._create_security_protection_app(
            overrides={
                "runtime": {
                    "cache": {
                        "backend": "redis",
                        "key_prefix": key_prefix,
                        "backend_detail": {
                            "kind": "redis_cache_backend",
                            "schema_version": "1.0",
                            "redis_url": REDIS_CACHE_URL,
                            "socket_connect_timeout_seconds": (
                                REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS
                            ),
                            "max_connections": REDIS_INTEGRATION_MAX_CONNECTIONS,
                        },
                    },
                    "security": {"detail": {"protection": {"ip_block": {"enabled": False}}}},
                }
            }
        )

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            create_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_CREATE_KIND,
                    IP_DIGEST_FIELD: ip_digest,
                    REASON_FIELD: SecurityIpBlockReason.MANUAL.value,
                    BLOCK_SECONDS_FIELD: MANUAL_BLOCK_SECONDS,
                },
            )
            record = create_response.json()[DATA_FIELD][RECORD_FIELD]
            cache_key = self._build_ip_block_cache_key(
                key_prefix=key_prefix,
                ip_digest=ip_digest,
            )
            cached_before_release = app.state.container.resource_mount.get_cache_store().get_value(
                cache_key
            )
            release_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_RELEASE_KIND,
                    IP_DIGEST_FIELD: ip_digest,
                    RELEASED_REASON_FIELD: RELEASED_REASON,
                },
            )
            cached_after_release = app.state.container.resource_mount.get_cache_store().get_value(
                cache_key
            )
            released_list_response = client.get(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                params={
                    STATUS_FIELD: SecurityIpBlockStatus.RELEASED.value,
                    IP_DIGEST_FIELD: ip_digest,
                },
            )

        released_records = released_list_response.json()[DATA_FIELD][RECORDS_FIELD]

        assert create_response.status_code == HTTPStatus.OK
        assert record[RECORD_ID_FIELD] is not None
        assert cached_before_release is not None
        assert release_response.status_code == HTTPStatus.OK
        assert cached_after_release is None
        assert any(
            released_record[STATUS_FIELD] == SecurityIpBlockStatus.RELEASED.value
            and released_record[IP_DIGEST_FIELD] == ip_digest
            for released_record in released_records
        )

    def test_ip_block_should_backfill_redis_from_database_record(self) -> None:
        """
        验证 Redis miss 时会从真实数据库有效封禁记录回填缓存。
        """

        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=REDIS_CACHE_URL,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        key_prefix = REDIS_IP_BLOCK_KEY_PREFIX_TEMPLATE.format(suffix=uuid4().hex)
        app = self._create_security_protection_app(
            overrides=self._build_redis_cache_overrides(key_prefix=key_prefix)
        )

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            ip_digest = resource_mount.get_sensitive_digest_service().digest(
                REDIS_BACKFILL_CLIENT_IP
            )
            cache_key = self._build_ip_block_cache_key(
                key_prefix=key_prefix,
                ip_digest=ip_digest,
            )
            resource_mount.get_cache_store().delete_value(cache_key)
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                repository = resource_mount.create_security_ip_block_repository(session)
                repository.create_block_record(
                    ip_digest=ip_digest,
                    reason=SecurityIpBlockReason.MANUAL,
                    blocked_until_epoch=int(time.time()) + MANUAL_BLOCK_SECONDS,
                )
                unit_of_work.commit()
            except Exception:
                unit_of_work.rollback()
                raise
            finally:
                unit_of_work.dispose()

            result = resource_mount.get_ip_block_guard().evaluate(
                self._build_request(client_ip=REDIS_BACKFILL_CLIENT_IP),
                cache_ttl_seconds=IP_BLOCK_CACHE_TTL_SECONDS,
            )
            cached_value = resource_mount.get_cache_store().get_value(cache_key)

        assert result.blocked is True
        assert cached_value is not None

    def _build_request(self, client_ip: str = "127.0.0.1") -> Request:
        """
        构建请求。
        """

        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": [],
                "client": (client_ip, 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )

    def _issue_admin_token(self, client: TestClient) -> str:
        """
        签发管理访问令牌。
        """

        token_response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        return str(token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD])

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构造授权请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _build_ip_block_cache_key(self, *, key_prefix: str, ip_digest: str) -> str:
        """
        构造 IP 封禁缓存键。
        """

        return CacheKeyBuilder(key_prefix=key_prefix).build(
            namespace=CacheNamespace.IP_BLOCK,
            key_parts=[IP_BLOCK_CACHE_SEGMENT, ip_digest],
        )

    def _delete_ip_block_records(self, *, app: FastAPI, ip_digest: str) -> None:
        """
        清理测试写入的 IP 封禁记录。
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            (
                session.query(SecurityIpBlockRecordOrmModel)
                .filter(SecurityIpBlockRecordOrmModel.ip_digest == ip_digest)
                .delete()
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _build_redis_cache_overrides(self, *, key_prefix: str) -> dict[str, object]:
        """
        构造 Redis 缓存测试覆盖配置。
        """

        return {
            "runtime": {
                "cache": {
                    "backend": "redis",
                    "key_prefix": key_prefix,
                    "backend_detail": {
                        "kind": "redis_cache_backend",
                        "schema_version": "1.0",
                        "redis_url": REDIS_CACHE_URL,
                        "socket_connect_timeout_seconds": (REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS),
                        "max_connections": REDIS_INTEGRATION_MAX_CONNECTIONS,
                    },
                },
                "security": {"detail": {"protection": {"ip_block": {"enabled": False}}}},
            }
        }

    def _create_security_protection_app(
        self,
        *,
        overrides: SettingsOverrideMapping | None = None,
    ) -> FastAPI:
        """
        创建显式启用安全防护模块的测试应用。
        """

        return TestAppFactory().create(
            overrides=self._merge_security_protection_module_overrides(overrides)
        )

    def _security_protection_module_overrides(self) -> SettingsOverrideMapping:
        """
        构建安全防护模块启用覆盖配置。
        """

        return {
            "app": {
                "modules": {
                    "enabled": SECURITY_PROTECTION_ENABLED_MODULES,
                }
            }
        }

    def _merge_security_protection_module_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping:
        """
        合并安全防护模块启用覆盖配置。
        """

        module_overrides = self._security_protection_module_overrides()
        if overrides is None:
            return module_overrides
        return SettingsMappingMerger().merge(module_overrides, overrides)
