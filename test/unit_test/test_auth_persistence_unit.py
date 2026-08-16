"""
测试鉴权持久化单元测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.application.refresh_access_token_usecase import (
    REFRESH_TOKEN_THROTTLE_GLOBAL_FIELD,
    RefreshTokenInput,
)
from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.auth_contract.authorization_policy_contract import AuthorizationPolicy
from src.core.auth_contract.token_payload_contract import TokenUse
from src.core.persistence_contract.refresh_token_repository_contract import (
    RefreshTokenSessionPayload,
)
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.domain.auth.authorization_policy_evaluator import (
    AuthorizationPolicyEvaluator,
)
from src.infrastructure.auth.auth_failure_throttle import AuthFailureThrottle
from src.infrastructure.auth.jwt_token_service import JwtTokenService
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_service import CacheService
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_scope_orm_model import AuthScopeOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_scope_orm_model import (
    AuthUserScopeOrmModel,
)
from src.infrastructure.settings.application_settings import (
    AuthRuntimeSettings,
    PasswordHashAlgorithm,
)
from src.infrastructure.testing.cache_policy_test_support import CachePolicyTestFactory
from src.infrastructure.testing.fake_cache_store import FakeCacheStore
from src.infrastructure.testing.fake_clock import FakeClock

AUTH_CACHE_KEY_PREFIX = "auth_unit_cache"
AUTH_FAILURE_WINDOW_SECONDS = 30
DEFAULT_THROTTLE_LOCK_SECONDS = 20
EXPECTED_REVOKED_SESSION_RECORD_COUNT = 2
EXPIRED_SESSION_OFFSET_MINUTES = 1
REFRESH_SESSION_EXPIRES_IN_MINUTES = 5
CONFLICT_USERNAME_PREFIX = "conflict-user"
CONFLICT_SUBJECT_PREFIX = "user-conflict"
CONFLICT_PASSWORD_HASH = "conflict-password-hash"
REFRESH_THROTTLE_TOKEN = "refresh-token-value"
REFRESH_THROTTLE_SECOND_TOKEN = "refresh-token-second-value"
REFRESH_THROTTLE_FIRST_IP = "198.51.100.10"
REFRESH_THROTTLE_SECOND_IP = "198.51.100.11"
ADMIN_SUBJECT_ID = "user-admin"
ADMIN_USERNAME = "admin"
EXPECTED_REFRESH_THROTTLE_SUBJECT_KEY_COUNT = 2


class TestAuthPersistenceUnit:
    """
    测试鉴权持久化单元测试集合，用于组织同一主题下的测试场景。
    """

    def test_password_hasher_should_hash_and_verify_password(self) -> None:
        """
        验证密码哈希器应哈希与校验密码。

        :returns: 无返回值。
        :rtype: None
        """

        password_hasher = PasswordHasher(PasswordHashAlgorithm.ARGON2)
        password_hash = password_hasher.hash_password("admin")

        assert password_hash != "admin"
        assert password_hasher.verify_password("admin", password_hash) is True
        assert password_hasher.needs_rehash(password_hash) is False

    def test_jwt_token_service_should_keep_shared_session_id(self) -> None:
        """
        验证JWT令牌服务应保持共享会话标识。

        :returns: 无返回值。
        :rtype: None
        """

        principal = AuthenticatedPrincipal(
            subject_id="user-1",
            username="tester",
            roles=[AuthRoleKey.ADMIN],
            scopes=[AuthScopeCode.SYSTEM_READ],
        )
        token_service = JwtTokenService(
            AccessTokenPolicy(
                jwt_secret="auth-persistence-secret-2026-with-safe-length",
                jwt_algorithm="HS256",
                access_token_expires_in_seconds=30,
                refresh_token_expires_in_seconds=60,
                issuer="unit",
                audience="client",
                refresh_token_rotation_enabled=True,
            )
        )

        issued_token_bundle = token_service.issue_token_pair(principal, current_epoch=10)
        access_token_payload = token_service.decode_token(
            issued_token_bundle.response_payload.access_token,
            expected_use=TokenUse.ACCESS,
            current_epoch=15,
        )
        refresh_token_payload = token_service.decode_token(
            issued_token_bundle.response_payload.refresh_token,
            expected_use=TokenUse.REFRESH,
            current_epoch=15,
        )

        assert access_token_payload.token_session_id == refresh_token_payload.token_session_id
        assert access_token_payload.token_id != refresh_token_payload.token_id

    def test_auth_failure_throttle_should_lock_after_failure_limit(self) -> None:
        """
        验证鉴权失败节流应锁定之后失败限制。

        :returns: 无返回值。
        :rtype: None
        :raises AssertionError: 当当前步骤检测到异常条件时抛出。
        """

        fake_clock = FakeClock(initial_value=100)
        throttle = AuthFailureThrottle(
            cache_service=self._build_cache_service(fake_clock=fake_clock),
            settings=self._build_auth_runtime_settings(),
            timer=lambda: int(fake_clock.now()),
        )
        throttle.record_issue_access_token_failure("admin")
        throttle.record_issue_access_token_failure("admin")
        try:
            throttle.assert_issue_access_token_allowed("admin")
        except Exception as exc:
            assert "请求过于频繁" in str(exc)
        else:
            raise AssertionError("预期触发频控锁定。")

    def test_auth_failure_throttle_should_recover_after_lock_window(self) -> None:
        """
        验证鉴权失败节流应恢复之后锁定窗口。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock(initial_value=100)
        throttle = AuthFailureThrottle(
            cache_service=self._build_cache_service(fake_clock=fake_clock),
            settings=self._build_auth_runtime_settings(),
            timer=lambda: int(fake_clock.now()),
        )

        throttle.record_issue_access_token_failure("admin")
        throttle.record_issue_access_token_failure("admin")
        with pytest.raises(Exception) as fault:
            throttle.assert_issue_access_token_allowed("admin")
        assert getattr(fault.value, "status_code", None) == HTTPStatus.TOO_MANY_REQUESTS
        assert getattr(fault.value, "error_code", None) == str(AuthErrorCode.REQUEST_THROTTLED)

        fake_clock.advance(DEFAULT_THROTTLE_LOCK_SECONDS + 1)
        throttle.assert_issue_access_token_allowed("admin")

    def test_refresh_throttle_subject_should_use_ip_and_global_keys(self) -> None:
        """
        验证刷新令牌节流主体使用客户端 IP 与全局维度。
        """

        fake_clock = FakeClock(initial_value=100)
        throttle = AuthFailureThrottle(
            cache_service=self._build_cache_service(fake_clock=fake_clock),
            settings=self._build_auth_runtime_settings(),
            timer=lambda: int(fake_clock.now()),
        )
        first_subject_key = RefreshTokenInput(
            refresh_token=REFRESH_THROTTLE_TOKEN,
            client_ip=REFRESH_THROTTLE_FIRST_IP,
        ).build_throttle_subject_key()
        same_ip_subject_key = RefreshTokenInput(
            refresh_token=REFRESH_THROTTLE_SECOND_TOKEN,
            client_ip=REFRESH_THROTTLE_FIRST_IP,
        ).build_throttle_subject_key()
        other_ip_subject_key = RefreshTokenInput(
            refresh_token=REFRESH_THROTTLE_TOKEN,
            client_ip=REFRESH_THROTTLE_SECOND_IP,
        ).build_throttle_subject_key()
        subject_keys = RefreshTokenInput(
            refresh_token=REFRESH_THROTTLE_TOKEN,
            client_ip=REFRESH_THROTTLE_FIRST_IP,
        ).build_throttle_subject_keys()
        global_subject_key = next(
            subject_key
            for subject_key in subject_keys
            if REFRESH_TOKEN_THROTTLE_GLOBAL_FIELD in subject_key
        )

        throttle.record_refresh_access_token_failure(first_subject_key)
        throttle.record_refresh_access_token_failure(first_subject_key)

        with pytest.raises(Exception) as fault:
            throttle.assert_refresh_access_token_allowed(same_ip_subject_key)
        throttle.assert_refresh_access_token_allowed(other_ip_subject_key)

        throttle.record_refresh_access_token_failure(global_subject_key)
        throttle.record_refresh_access_token_failure(global_subject_key)
        with pytest.raises(Exception) as global_fault:
            throttle.assert_refresh_access_token_allowed(global_subject_key)

        assert first_subject_key == same_ip_subject_key
        assert first_subject_key != other_ip_subject_key
        assert len(subject_keys) == EXPECTED_REFRESH_THROTTLE_SUBJECT_KEY_COUNT
        assert any(
            REFRESH_TOKEN_THROTTLE_GLOBAL_FIELD in subject_key for subject_key in subject_keys
        )
        assert all(REFRESH_THROTTLE_TOKEN not in key for key in subject_keys)
        assert getattr(fault.value, "status_code", None) == HTTPStatus.TOO_MANY_REQUESTS
        assert getattr(global_fault.value, "status_code", None) == HTTPStatus.TOO_MANY_REQUESTS

    def test_auth_identity_repository_should_return_authorization_snapshot(
        self,
    ) -> None:
        """
        验证鉴权身份仓储应返回授权快照。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                repository = resource_mount.create_auth_identity_repository(
                    unit_of_work.get_session()
                )
                snapshot = repository.get_authorization_snapshot_by_subject_id(ADMIN_SUBJECT_ID)
                assert snapshot is not None
                assert snapshot.subject_id == ADMIN_SUBJECT_ID
                assert snapshot.username == ADMIN_USERNAME
                assert snapshot.roles == [AuthRoleKey.ADMIN]
                assert AuthScopeCode.AUTH_READ in snapshot.scopes
            finally:
                unit_of_work.dispose()

    def test_auth_identity_repository_when_scope_disabled_should_fail_closed(
        self,
    ) -> None:
        """
        验证禁用 scope 后鉴权身份仓储不再返回该授权作用域。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                scope_row = session.get(AuthScopeOrmModel, AuthScopeCode.AUTH_READ.value)
                assert scope_row is not None
                scope_row.enabled = False
                unit_of_work.flush()

                repository = resource_mount.create_auth_identity_repository(session)
                snapshot = repository.get_authorization_snapshot_by_subject_id(ADMIN_SUBJECT_ID)
                assert snapshot is not None
                decision = AuthorizationPolicyEvaluator().evaluate(
                    AuthenticatedPrincipal(
                        subject_id=snapshot.subject_id,
                        username=snapshot.username,
                        roles=snapshot.roles,
                        scopes=snapshot.scopes,
                    ),
                    AuthorizationPolicy(required_scopes=[AuthScopeCode.AUTH_READ]),
                )

                assert AuthScopeCode.AUTH_READ not in snapshot.scopes
                assert decision.allowed is False
            finally:
                unit_of_work.rollback()
                unit_of_work.dispose()

    def test_auth_identity_repository_should_union_role_and_direct_scopes(self) -> None:
        """验证主体 scope 是角色授权与用户直接授权的有效并集。"""

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                user = session.query(AuthUserOrmModel).filter_by(subject_id=ADMIN_SUBJECT_ID).one()
                user.user_scopes.append(
                    AuthUserScopeOrmModel(scope_code=AuthScopeCode.CODEX_NETWORK.value)
                )
                unit_of_work.flush()

                repository = resource_mount.create_auth_identity_repository(session)
                snapshot = repository.get_authorization_snapshot_by_subject_id(ADMIN_SUBJECT_ID)

                assert snapshot is not None
                assert AuthScopeCode.AUTH_READ in snapshot.scopes
                assert AuthScopeCode.CODEX_NETWORK in snapshot.scopes
                assert snapshot.scopes.count(AuthScopeCode.CODEX_NETWORK) == 1
            finally:
                unit_of_work.rollback()
                unit_of_work.dispose()

    def test_bootstrap_admin_synchronizer_should_keep_role_scope_binding_isolated(
        self,
    ) -> None:
        """
        验证引导管理员同步器应保持角色作用域绑定隔离。

        :returns: 无返回值。
        :rtype: None
        """

        bootstrap_username = "bootstrap-isolation-admin"
        bootstrap_subject_id = "user-bootstrap-isolation-admin"
        admin_role_key = "bootstrap-isolation-admin-role"
        auditor_role_key = "bootstrap-isolation-auditor-role"
        app = TestAppFactory().create(
            overrides={
                "auth_module": {
                    "bootstrap_admin": {
                        "enabled": True,
                        "username": bootstrap_username,
                        "subject_id": bootstrap_subject_id,
                        "role_bindings": [
                            {
                                "kind": "bootstrap_role_binding",
                                "schema_version": "v1",
                                "role_key": admin_role_key,
                                "scope_codes": ["auth:read", "system:read"],
                            },
                            {
                                "kind": "bootstrap_role_binding",
                                "schema_version": "v1",
                                "role_key": auditor_role_key,
                                "scope_codes": ["system:read"],
                            },
                        ],
                    }
                }
            }
        )
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                unit_of_work = resource_mount.create_unit_of_work()
                try:
                    session = unit_of_work.get_session()
                    user = (
                        session.query(AuthUserOrmModel).filter_by(username=bootstrap_username).one()
                    )
                    assert {user_role.role.role_key for user_role in user.user_roles} == {
                        admin_role_key,
                        auditor_role_key,
                    }
                    role_scope_mapping = {
                        role.role_key: sorted(
                            role_scope.scope_code for role_scope in role.role_scopes
                        )
                        for role in session.query(AuthRoleOrmModel)
                        .filter(AuthRoleOrmModel.role_key.in_([admin_role_key, auditor_role_key]))
                        .all()
                    }
                    assert role_scope_mapping[admin_role_key] == [
                        "auth:read",
                        "system:read",
                    ]
                    assert role_scope_mapping[auditor_role_key] == ["system:read"]
                finally:
                    unit_of_work.dispose()
            finally:
                self._cleanup_bootstrap_identity(
                    resource_mount=resource_mount,
                    username=bootstrap_username,
                    role_keys=[admin_role_key, auditor_role_key],
                )

    def test_refresh_token_repository_should_revoke_all_active_sessions(self) -> None:
        """
        验证刷新令牌仓储应支持全量失效活跃会话。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
                repository = resource_mount.create_refresh_token_repository(session)
                active_session = self._build_refresh_token_session(user.user_id)
                revoked_session = self._build_refresh_token_session(
                    user.user_id,
                    revoked_at=datetime.now(UTC),
                )
                repository.create(active_session)
                repository.create(revoked_session)
                revoked_count = repository.revoke_all_active_token_sessions(
                    revoked_at=datetime.now(UTC)
                )
                unit_of_work.commit()
                active_snapshot = repository.get_by_token_id(active_session.refresh_token_id)
                revoked_snapshot = repository.get_by_token_id(revoked_session.refresh_token_id)

                assert revoked_count >= 1
                assert active_snapshot is not None
                assert active_snapshot.revoked_at is not None
                assert revoked_snapshot is not None
                assert revoked_snapshot.revoked_at is not None
            finally:
                unit_of_work.dispose()

    def test_refresh_token_repository_should_revoke_active_records_by_session(self) -> None:
        """
        验证刷新令牌仓储应按令牌会话撤销活跃记录。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
                repository = resource_mount.create_refresh_token_repository(session)
                token_session_id = uuid4()
                other_token_session_id = uuid4()
                first_active_session = self._build_refresh_token_session(
                    user.user_id,
                    token_session_id=token_session_id,
                )
                second_active_session = self._build_refresh_token_session(
                    user.user_id,
                    token_session_id=token_session_id,
                )
                other_active_session = self._build_refresh_token_session(
                    user.user_id,
                    token_session_id=other_token_session_id,
                )
                revoked_at = datetime.now(UTC)
                repository.create(first_active_session)
                repository.create(second_active_session)
                repository.create(other_active_session)
                revoked_count = repository.revoke_token_session(
                    token_session_id=token_session_id,
                    revoked_at=revoked_at,
                )
                unit_of_work.commit()
                first_snapshot = repository.get_by_token_id(first_active_session.refresh_token_id)
                second_snapshot = repository.get_by_token_id(second_active_session.refresh_token_id)
                other_snapshot = repository.get_by_token_id(other_active_session.refresh_token_id)

                assert revoked_count == EXPECTED_REVOKED_SESSION_RECORD_COUNT
                assert first_snapshot is not None
                assert first_snapshot.revoked_at == revoked_at
                assert second_snapshot is not None
                assert second_snapshot.revoked_at == revoked_at
                assert other_snapshot is not None
                assert other_snapshot.revoked_at is None
            finally:
                unit_of_work.dispose()

    def test_refresh_token_session_status_should_mark_expired_active_session(
        self,
    ) -> None:
        """
        验证刷新令牌会话状态应识别已过期但未撤销的会话。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
                repository = resource_mount.create_refresh_token_repository(session)
                expired_session = self._build_refresh_token_session(
                    user.user_id,
                    expires_at=datetime.now(UTC)
                    - timedelta(minutes=EXPIRED_SESSION_OFFSET_MINUTES),
                )

                repository.create(expired_session)
                unit_of_work.flush()
                status = repository.get_token_session_status(expired_session.token_session_id)

                assert status is not None
                assert status.is_expired is True
                assert status.is_revoked is False
            finally:
                unit_of_work.rollback()
                unit_of_work.dispose()

    def test_refresh_token_session_status_when_subject_conflict_should_not_raise(
        self,
    ) -> None:
        """
        验证同一会话出现主体冲突时应返回不一致状态而非未映射异常。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
                conflict_user = AuthUserOrmModel(
                    user_id=uuid4(),
                    subject_id=f"{CONFLICT_SUBJECT_PREFIX}-{uuid4()}",
                    username=f"{CONFLICT_USERNAME_PREFIX}-{uuid4()}",
                    password_hash=CONFLICT_PASSWORD_HASH,
                    is_active=True,
                )
                session.add(conflict_user)
                unit_of_work.flush()
                repository = resource_mount.create_refresh_token_repository(session)
                token_session_id = uuid4()
                repository.create(
                    self._build_refresh_token_session(
                        user.user_id,
                        token_session_id=token_session_id,
                        subject_id=user.subject_id,
                    )
                )
                repository.create(
                    self._build_refresh_token_session(
                        conflict_user.user_id,
                        token_session_id=token_session_id,
                        subject_id=conflict_user.subject_id,
                    )
                )
                unit_of_work.flush()

                status = repository.get_token_session_status(token_session_id)

                assert status is not None
                assert status.is_inconsistent is True
                assert status.is_revoked is True
            finally:
                unit_of_work.rollback()
                unit_of_work.dispose()

    def test_refresh_token_session_status_when_active_token_duplicated_should_inconsistent(
        self,
    ) -> None:
        """
        验证同一会话出现多个活跃刷新令牌时应返回不一致状态。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
                repository = resource_mount.create_refresh_token_repository(session)
                token_session_id = uuid4()
                repository.create(
                    self._build_refresh_token_session(
                        user.user_id,
                        token_session_id=token_session_id,
                        subject_id=user.subject_id,
                    )
                )
                repository.create(
                    self._build_refresh_token_session(
                        user.user_id,
                        token_session_id=token_session_id,
                        subject_id=user.subject_id,
                    )
                )
                unit_of_work.flush()

                status = repository.get_token_session_status(token_session_id)

                assert status is not None
                assert status.is_inconsistent is True
                assert status.is_revoked is True
            finally:
                unit_of_work.rollback()
                unit_of_work.dispose()

    def _cleanup_bootstrap_identity(
        self,
        *,
        resource_mount,
        username: str,
        role_keys: list[str],
    ) -> None:
        """
        处理清理引导身份。

        :param resource_mount: 共享资源挂载点，用于访问数据库、缓存、消息和鉴权能力。
        :type resource_mount: Any
        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :param role_keys: 角色键列表。约束：需符合 ``list[str]`` 注解。
        :type role_keys: list[str]
        :returns: 无返回值。
        :rtype: None
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user = session.query(AuthUserOrmModel).filter_by(username=username).one_or_none()
            if user is not None:
                session.delete(user)
            roles = (
                session.query(AuthRoleOrmModel)
                .filter(AuthRoleOrmModel.role_key.in_(role_keys))
                .all()
            )
            for role in roles:
                session.delete(role)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _build_cache_service(self, *, fake_clock: FakeClock) -> CacheService:
        """
        构建缓存服务。

        :param fake_clock: 当前步骤使用的模拟时钟参数。约束：需符合 ``FakeClock`` 注解。
        :type fake_clock: FakeClock
        :returns: 返回当前操作结果。
        :rtype: CacheService
        """

        return CacheService(
            cache_store=FakeCacheStore(timer=fake_clock.now),
            key_builder=CacheKeyBuilder(key_prefix=AUTH_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=AUTH_FAILURE_WINDOW_SECONDS,
            ),
            default_ttl_seconds=AUTH_FAILURE_WINDOW_SECONDS,
        )

    def _build_refresh_token_session(
        self,
        user_id: UUID,
        *,
        token_session_id: UUID | None = None,
        subject_id: str = "user-admin",
        expires_at: datetime | None = None,
        revoked_at: datetime | None = None,
    ) -> RefreshTokenSessionPayload:
        """
        构建刷新令牌会话测试载荷。
        """

        issued_at = datetime.now(UTC)
        return RefreshTokenSessionPayload(
            refresh_token_id=uuid4(),
            token_session_id=token_session_id or uuid4(),
            user_id=user_id,
            subject_id=subject_id,
            issued_at=issued_at,
            expires_at=expires_at
            or issued_at + timedelta(minutes=REFRESH_SESSION_EXPIRES_IN_MINUTES),
            revoked_at=revoked_at,
        )

    def _build_auth_runtime_settings(self) -> AuthRuntimeSettings:
        """
        构建鉴权运行时配置。

        :returns: 返回当前操作结果。
        :rtype: AuthRuntimeSettings
        """

        return AuthRuntimeSettings(
            jwt_secret="secret",
            jwt_algorithm="HS256",
            access_token_expires_in_seconds=30,
            refresh_token_expires_in_seconds=60,
            issuer="unit",
            audience="client",
            password_hash_algorithm=PasswordHashAlgorithm.ARGON2,
            refresh_token_rotation_enabled=True,
            issue_access_token_failure_limit=2,
            issue_access_token_failure_window_seconds=AUTH_FAILURE_WINDOW_SECONDS,
            refresh_access_token_failure_limit=2,
            refresh_access_token_failure_window_seconds=AUTH_FAILURE_WINDOW_SECONDS,
            throttle_lock_seconds=DEFAULT_THROTTLE_LOCK_SECONDS,
        )
