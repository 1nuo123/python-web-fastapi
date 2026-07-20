"""
密钥管理服务单元测试模块。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import TokenUse
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.key_management_contract.key_management_contract import (
    ManagedKeyFamilyEnvelope,
)
from src.core.key_management_contract.key_ring_contract import (
    KeyRingSnapshot,
    ManagedKeyStatus,
)
from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.infrastructure.auth.jwt_token_service import JwtTokenService
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import (
    DistributedLockProvider,
)
from src.infrastructure.key_management.database_key_ring_store import (
    KEY_RING_CACHE_SEGMENT,
    DatabaseKeyRingStore,
)
from src.infrastructure.key_management.key_management_service import (
    KEY_MANAGEMENT_ROTATION_CAS_FAILED_MESSAGE,
    KeyManagementService,
)
from src.infrastructure.key_management.key_rotation_service import KeyRotationService
from src.infrastructure.key_management.redis_key_ring_store import RedisKeyRingStore
from src.infrastructure.persistence.orm_model.key_ring_snapshot_orm_model import (
    KeyRingSnapshotOrmModel,
)
from src.infrastructure.persistence.sqlalchemy_metadata_registry import OrmModelBase
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
)

JWT_SECRET = "jwt-secret"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "unit"
JWT_AUDIENCE = "client"
JWT_ACCESS_SECONDS = 60
JWT_REFRESH_SECONDS = 120
JWT_REFRESH_ROTATION_ENABLED = True
JWT_INITIAL_EPOCH = 1000
JWT_ROTATED_EPOCH = 1011
JWT_SUBJECT_ID = "user-key-management"
JWT_USERNAME = "key-management-user"
JWT_ROLE = "admin"
JWT_SCOPE = "auth:read"
KEY_RING_NEXT_ROTATION_STEP_SECONDS = 1
KEY_RING_TEST_CACHE_PREFIX = "unit"
KEY_RING_TEST_FAMILY_NAME = "jwt_signing"
KEY_RING_TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"
KEY_RING_TEST_ENCRYPTION_SECRET = "unit-key-ring-encryption-secret-2026"
KEY_RING_RAW_MATERIAL_FIELD_NAME = "key_material"
KEY_RING_RAW_FAMILY_FIELD_NAME = "key_family"


class CasFailingRedisKeyRingStore(RedisKeyRingStore):
    """
    CAS 写入失败的密钥环存储测试替身。
    """

    def save_key_ring_if_version_matches(
        self,
        *,
        current_snapshot: KeyRingSnapshot,
        next_snapshot: KeyRingSnapshot,
    ) -> bool:
        """
        始终拒绝轮转 CAS 写入。
        """

        _ = current_snapshot
        _ = next_snapshot
        return False


class TestKeyManagementServiceUnit:
    """
    密钥管理服务单元测试集合。
    """

    def test_initialize_key_family_should_be_idempotent(self) -> None:
        """
        验证密钥族初始化幂等。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="unit")
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            key_rotation_service=KeyRotationService(),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
        )
        key_family = self._build_key_family()

        first_snapshot = service.initialize_key_family(key_family)
        second_snapshot = service.initialize_key_family(key_family)

        assert first_snapshot.current_key_id == second_snapshot.current_key_id
        assert service.get_current_key("jwt_signing").key_id == first_snapshot.current_key_id
        cache_store.close()

    def test_rotated_previous_key_should_be_readable_by_key_id(self) -> None:
        """
        验证轮转后的旧密钥在兼容窗口内可按 key id 读取。
        """

        current_time = 1000.0
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            key_rotation_service=KeyRotationService(timer=lambda: current_time),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
                timer=lambda: current_time,
            ),
        )
        key_family = ManagedKeyFamilyEnvelope(
            family_name="jwt_signing",
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=10,
                active_key_count=2,
                compatibility_window_seconds=30,
            ),
        )
        initial_snapshot = service.initialize_key_family(key_family)
        previous_key_id = initial_snapshot.current_key_id
        current_time = 1011.0

        service.rotate_key_family_if_due(key_family)
        previous_key = service.get_key_by_id("jwt_signing", previous_key_id)

        assert previous_key.key_id == previous_key_id
        cache_store.close()

    def test_get_current_key_should_rotate_known_family_when_due(self) -> None:
        """
        验证读取当前密钥时会对已注册密钥族执行到期轮转。
        """

        current_time = 1000.0
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            key_rotation_service=KeyRotationService(timer=lambda: current_time),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
                timer=lambda: current_time,
            ),
        )
        key_family = ManagedKeyFamilyEnvelope(
            family_name="jwt_signing",
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=10,
                active_key_count=2,
                compatibility_window_seconds=30,
            ),
        )
        initial_snapshot = service.initialize_key_family(key_family)
        current_time = 1011.0

        current_key = service.get_current_key("jwt_signing")

        assert current_key.key_id != initial_snapshot.current_key_id
        cache_store.close()

    def test_key_ring_store_should_compare_and_set_by_snapshot_version(self) -> None:
        """
        验证密钥环存储使用当前快照 JSON 执行 CAS 保存。
        """

        cache_store = MemoryCacheStore()
        try:
            key_ring_store = RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=CacheKeyBuilder(key_prefix="unit"),
            )
            initial_snapshot = KeyRotationService().build_initial_key_ring(
                key_family="jwt_signing",
                rotation_policy=self._build_key_family().rotation_policy,
            )
            next_snapshot = initial_snapshot.model_copy(
                update={
                    "next_rotation_epoch": (
                        initial_snapshot.next_rotation_epoch + KEY_RING_NEXT_ROTATION_STEP_SECONDS
                    )
                }
            )

            initial_saved = key_ring_store.save_key_ring_if_absent(initial_snapshot)
            cas_saved = key_ring_store.save_key_ring_if_version_matches(
                current_snapshot=initial_snapshot,
                next_snapshot=next_snapshot,
            )
            stale_saved = key_ring_store.save_key_ring_if_version_matches(
                current_snapshot=initial_snapshot,
                next_snapshot=next_snapshot,
            )

            loaded_snapshot = key_ring_store.load_key_ring("jwt_signing")

            assert initial_saved is True
            assert cas_saved is True
            assert stale_saved is False
            assert loaded_snapshot is not None
            assert loaded_snapshot.next_rotation_epoch == next_snapshot.next_rotation_epoch
        finally:
            cache_store.close()

    def test_database_key_ring_store_should_encrypt_persist_and_refresh_cache(
        self,
    ) -> None:
        """
        验证数据库密钥环存储加密持久化并刷新缓存镜像。
        """

        engine = create_engine(KEY_RING_TEST_DATABASE_URL, future=True)
        cache_store = MemoryCacheStore()
        try:
            OrmModelBase.metadata.create_all(
                engine,
                tables=[KeyRingSnapshotOrmModel.__table__],
            )
            session_factory = SqlAlchemySessionFactory(engine)
            key_ring_store = DatabaseKeyRingStore(
                unit_of_work_factory=session_factory.create_unit_of_work,
                cache_store=cache_store,
                key_builder=CacheKeyBuilder(key_prefix=KEY_RING_TEST_CACHE_PREFIX),
                encryption_secret=KEY_RING_TEST_ENCRYPTION_SECRET,
            )
            initial_snapshot = KeyRotationService().build_initial_key_ring(
                key_family=KEY_RING_TEST_FAMILY_NAME,
                rotation_policy=self._build_key_family().rotation_policy,
            )
            next_snapshot = initial_snapshot.model_copy(
                update={
                    "next_rotation_epoch": (
                        initial_snapshot.next_rotation_epoch + KEY_RING_NEXT_ROTATION_STEP_SECONDS
                    )
                }
            )

            initial_saved = key_ring_store.save_key_ring_if_absent(initial_snapshot)
            duplicate_saved = key_ring_store.save_key_ring_if_absent(initial_snapshot)
            cas_saved = key_ring_store.save_key_ring_if_version_matches(
                current_snapshot=initial_snapshot,
                next_snapshot=next_snapshot,
            )
            stale_saved = key_ring_store.save_key_ring_if_version_matches(
                current_snapshot=initial_snapshot,
                next_snapshot=next_snapshot,
            )
            loaded_snapshot = key_ring_store.load_key_ring(KEY_RING_TEST_FAMILY_NAME)
            cache_value = cache_store.get_value(
                CacheKeyBuilder(key_prefix=KEY_RING_TEST_CACHE_PREFIX).build(
                    namespace=CacheNamespace.KEY_RING,
                    key_parts=[KEY_RING_CACHE_SEGMENT, KEY_RING_TEST_FAMILY_NAME],
                )
            )

            with session_factory.create_session() as session:
                row = session.execute(select(KeyRingSnapshotOrmModel)).scalar_one()

            assert initial_saved is True
            assert duplicate_saved is False
            assert cas_saved is True
            assert stale_saved is False
            assert loaded_snapshot is not None
            assert loaded_snapshot.next_rotation_epoch == next_snapshot.next_rotation_epoch
            assert cache_value == next_snapshot.model_dump_json()
            assert KEY_RING_RAW_MATERIAL_FIELD_NAME not in row.encrypted_snapshot_json
            assert KEY_RING_RAW_FAMILY_FIELD_NAME not in row.encrypted_snapshot_json
        finally:
            cache_store.close()
            engine.dispose()

    def test_rotate_key_family_when_cas_failed_should_fail_closed(self) -> None:
        """
        验证密钥轮转 CAS 失败时按资源不可用 fail closed。
        """

        current_time = 1000.0
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        try:
            key_builder = CacheKeyBuilder(key_prefix="unit")
            service = KeyManagementService(
                key_ring_store=CasFailingRedisKeyRingStore(
                    cache_store=cache_store,
                    key_builder=key_builder,
                ),
                key_rotation_service=KeyRotationService(timer=lambda: current_time),
                distributed_lock_provider=DistributedLockProvider(
                    cache_store=cache_store,
                    key_builder=key_builder,
                    timer=lambda: current_time,
                ),
            )
            key_family = ManagedKeyFamilyEnvelope(
                family_name="jwt_signing",
                usage="jwt_signing",
                enabled=True,
                rotation_policy=KeyRotationPolicyEnvelope(
                    enabled=True,
                    rotation_interval_seconds=10,
                    active_key_count=2,
                    compatibility_window_seconds=30,
                ),
            )
            service.initialize_key_family(key_family)
            current_time = 1011.0

            with pytest.raises(HttpFaultException) as exc_info:
                service.rotate_key_family_if_due(key_family)

            assert exc_info.value.message == KEY_MANAGEMENT_ROTATION_CAS_FAILED_MESSAGE
        finally:
            cache_store.close()

    def test_key_snapshot_should_filter_expired_future_and_retired_keys(self) -> None:
        """
        验证有效密钥快照会过滤过期、未来生效和 retired 密钥。
        """

        current_time = 1000.0
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        key_ring_store = RedisKeyRingStore(
            cache_store=cache_store,
            key_builder=key_builder,
        )
        service = KeyManagementService(
            key_ring_store=key_ring_store,
            key_rotation_service=KeyRotationService(timer=lambda: current_time),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
                timer=lambda: current_time,
            ),
        )
        initial_snapshot = service.initialize_key_family(self._build_key_family())
        current_key = initial_snapshot.keys[0]
        future_key = current_key.model_copy(
            update={
                "key_id": "future-key",
                "key_digest": "future-key-digest",
                "key_material": "future-key-material-2026",
                "status": ManagedKeyStatus.ACTIVE,
                "not_before_epoch": 1001,
                "expires_at_epoch": 2000,
            }
        )
        expired_key = current_key.model_copy(
            update={
                "key_id": "expired-key",
                "key_digest": "expired-key-digest",
                "key_material": "expired-key-material-2026",
                "status": ManagedKeyStatus.ACTIVE,
                "not_before_epoch": 900,
                "expires_at_epoch": 1000,
            }
        )
        retired_key = current_key.model_copy(
            update={
                "key_id": "retired-key",
                "key_digest": "retired-key-digest",
                "key_material": "retired-key-material-2026",
                "status": ManagedKeyStatus.RETIRED,
                "not_before_epoch": 900,
                "expires_at_epoch": 2000,
            }
        )
        key_ring_store.save_key_ring(
            initial_snapshot.model_copy(
                update={"keys": [current_key, future_key, expired_key, retired_key]}
            )
        )

        filtered_snapshot = service.get_key_ring_snapshot("jwt_signing")

        assert [key.key_id for key in filtered_snapshot.keys] == [current_key.key_id]
        with pytest.raises(HttpFaultException):
            service.get_key_by_id("jwt_signing", future_key.key_id)
        with pytest.raises(HttpFaultException):
            service.get_key_by_id("jwt_signing", expired_key.key_id)
        with pytest.raises(HttpFaultException):
            service.get_key_by_id("jwt_signing", retired_key.key_id)
        cache_store.close()

    def test_jwt_service_should_verify_old_token_after_key_rotation(self) -> None:
        """
        验证 JWT 签发接入密钥管理后旧有效 key 仍可验签。
        """

        current_time = float(JWT_INITIAL_EPOCH)
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            key_rotation_service=KeyRotationService(timer=lambda: current_time),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
                timer=lambda: current_time,
            ),
        )
        key_family = ManagedKeyFamilyEnvelope(
            family_name="jwt_signing",
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=10,
                active_key_count=2,
                compatibility_window_seconds=30,
            ),
        )
        service.initialize_key_family(key_family)
        token_service = JwtTokenService(
            self._build_access_token_policy(),
            key_management_service=service,
        )
        old_bundle = token_service.issue_token_pair(
            self._build_principal(),
            current_epoch=JWT_INITIAL_EPOCH,
        )
        current_time = float(JWT_ROTATED_EPOCH)
        service.rotate_key_family_if_due(key_family)

        old_payload = token_service.decode_token(
            old_bundle.response_payload.access_token,
            expected_use=TokenUse.ACCESS,
            current_epoch=JWT_ROTATED_EPOCH,
        )
        new_bundle = token_service.issue_token_pair(
            self._build_principal(),
            current_epoch=JWT_ROTATED_EPOCH,
        )

        assert old_payload.subject_id == JWT_SUBJECT_ID
        assert old_bundle.response_payload.access_token != new_bundle.response_payload.access_token
        cache_store.close()

    def test_jwt_service_should_auto_rotate_signing_key_when_due(self) -> None:
        """
        验证 JWT 签发读取当前密钥时会自动触发密钥轮转。
        """

        current_time = float(JWT_INITIAL_EPOCH)
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        key_builder = CacheKeyBuilder(key_prefix="unit")
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            key_rotation_service=KeyRotationService(timer=lambda: current_time),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
                timer=lambda: current_time,
            ),
        )
        key_family = ManagedKeyFamilyEnvelope(
            family_name="jwt_signing",
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=10,
                active_key_count=2,
                compatibility_window_seconds=30,
            ),
        )
        service.initialize_key_family(key_family)
        token_service = JwtTokenService(
            self._build_access_token_policy(),
            key_management_service=service,
        )
        old_bundle = token_service.issue_token_pair(
            self._build_principal(),
            current_epoch=JWT_INITIAL_EPOCH,
        )
        current_time = float(JWT_ROTATED_EPOCH)

        new_bundle = token_service.issue_token_pair(
            self._build_principal(),
            current_epoch=JWT_ROTATED_EPOCH,
        )
        old_payload = token_service.decode_token(
            old_bundle.response_payload.access_token,
            expected_use=TokenUse.ACCESS,
            current_epoch=JWT_ROTATED_EPOCH,
        )

        assert old_payload.subject_id == JWT_SUBJECT_ID
        assert old_bundle.response_payload.access_token != new_bundle.response_payload.access_token
        cache_store.close()

    def _build_access_token_policy(self) -> AccessTokenPolicy:
        """
        构建 JWT 访问令牌策略。
        """

        return AccessTokenPolicy(
            jwt_secret=JWT_SECRET,
            jwt_algorithm=JWT_ALGORITHM,
            access_token_expires_in_seconds=JWT_ACCESS_SECONDS,
            refresh_token_expires_in_seconds=JWT_REFRESH_SECONDS,
            refresh_token_rotation_enabled=JWT_REFRESH_ROTATION_ENABLED,
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
        )

    def _build_principal(self) -> AuthenticatedPrincipal:
        """
        构建认证主体。
        """

        return AuthenticatedPrincipal(
            subject_id=JWT_SUBJECT_ID,
            username=JWT_USERNAME,
            roles=[JWT_ROLE],
            scopes=[JWT_SCOPE],
        )

    def _build_key_family(self) -> ManagedKeyFamilyEnvelope:
        """
        构建密钥族。
        """

        return ManagedKeyFamilyEnvelope(
            family_name="jwt_signing",
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=60,
                active_key_count=2,
            ),
        )
