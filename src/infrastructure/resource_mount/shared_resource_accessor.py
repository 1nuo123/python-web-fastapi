"""共享资源访问器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from http import HTTPStatus

from sqlalchemy.orm import Session

from src.application.authorization_guard import AuthorizationGuard
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.security_runtime_contract import IpBlockRuntimeDetail
from src.core.persistence_contract.auth_identity_repository_contract import (
    AuthIdentityRepository,
)
from src.core.persistence_contract.refresh_token_repository_contract import (
    RefreshTokenRepository,
)
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.domain.auth.authorization_policy_evaluator import (
    AuthorizationPolicyEvaluator,
)
from src.infrastructure.auth.auth_failure_throttle import AuthFailureThrottle
from src.infrastructure.auth.jwt_token_service import JwtTokenService
from src.infrastructure.auth.oauth2_scheme_provider import OAuth2SchemeProvider
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.cache.cache_service import CacheService
from src.infrastructure.concurrency.distributed_lock_provider import (
    DistributedLockProvider,
)
from src.infrastructure.context.request_context_manager_impl import (
    RequestContextManagerImpl,
)
from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge
from src.infrastructure.key_management.key_management_service import KeyManagementService
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)
from src.infrastructure.logging.log_event_builder import LogEventBuilder
from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
from src.infrastructure.persistence.repository_impl.admin_identity_repository_impl import (
    AdminIdentityRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.auth_identity_repository_impl import (
    AuthIdentityRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.refresh_token_repository_impl import (
    RefreshTokenRepositoryImpl,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
    SqlAlchemyUnitOfWork,
)
from src.infrastructure.request_execution_bridge import RequestExecutionBridge
from src.infrastructure.resource_mount.shared_resource_constants import (
    ASYNC_HTTP_CLIENT_NOT_READY_MESSAGE,
    AUTH_THROTTLE_NOT_READY_MESSAGE,
    CACHE_SERVICE_NOT_READY_MESSAGE,
    CACHE_STORE_NOT_READY_MESSAGE,
    CLIENT_IP_RESOLVER_NOT_READY_MESSAGE,
    DISTRIBUTED_LOCK_NOT_READY_MESSAGE,
    KEY_MANAGEMENT_NOT_READY_MESSAGE,
    LOGGER_RESOURCE_NOT_READY_MESSAGE,
    REQUEST_EXECUTION_BRIDGE_NOT_READY_MESSAGE,
    SECURITY_PROTECTION_NOT_READY_MESSAGE,
    SESSION_FACTORY_NOT_READY_MESSAGE,
    SYNC_HTTP_CLIENT_NOT_READY_MESSAGE,
    TASK_EXECUTION_STORE_NOT_READY_MESSAGE,
    UNIT_OF_WORK_NOT_READY_MESSAGE,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient
from src.infrastructure.resource_slot.shared_http_client import SharedHttpClient
from src.infrastructure.security.client_ip_resolver import (
    ClientIpResolver,
)
from src.infrastructure.security.ip_block_guard import IpBlockGuard
from src.infrastructure.security.outbound_url_safety_validator import (
    OutboundUrlSafetyValidator,
)
from src.infrastructure.security.risk_signal_guard import RiskSignalGuard
from src.infrastructure.security.security_event_builder import SecurityEventBuilder
from src.infrastructure.security.security_protection_guard import SecurityProtectionGuard
from src.infrastructure.security.token_binding_guard import TokenBindingGuard
from src.infrastructure.task.task_execution_store import TaskExecutionStore


class SharedResourceAccessor(SharedResourceLifecycle):
    """共享资源访问器门面。"""

    def get_request_context_manager(self) -> RequestContextManagerImpl:
        """
        获取请求上下文管理器。
        """

        return self._request_context_manager

    def get_password_hasher(self) -> PasswordHasher:
        """
        获取密码哈希器。
        """

        return self._auth_accessor.password_hasher

    def get_oauth2_scheme_provider(self) -> OAuth2SchemeProvider:
        """
        获取 OAuth2 方案提供器。
        """

        return self._auth_accessor.oauth2_scheme_provider

    def get_jwt_token_service(self) -> JwtTokenService:
        """
        获取 JWT 令牌服务。
        """

        return self._auth_accessor.jwt_token_service

    def get_authorization_policy_evaluator(
        self,
    ) -> AuthorizationPolicyEvaluator:
        """
        获取授权策略评估器。
        """

        return self._auth_accessor.authorization_policy_evaluator

    def get_authorization_guard(self) -> AuthorizationGuard:
        """
        获取授权守卫。
        """

        return self._auth_accessor.authorization_guard

    def get_auth_failure_throttle(self) -> AuthFailureThrottle:
        """
        获取鉴权失败节流器。
        """

        if self._auth_accessor.auth_failure_throttle is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=AUTH_THROTTLE_NOT_READY_MESSAGE,
            )
        return self._auth_accessor.auth_failure_throttle

    def get_session_factory(self) -> SqlAlchemySessionFactory:
        """
        获取会话工厂。
        """

        if self._session_factory is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SESSION_FACTORY_NOT_READY_MESSAGE,
            )
        return self._session_factory

    def create_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """
        创建单元工作。
        """

        if self._db_session_manager is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=UNIT_OF_WORK_NOT_READY_MESSAGE,
            )
        return self._db_session_manager.create_unit_of_work()

    def get_task_execution_store(self) -> TaskExecutionStore:
        """
        获取任务执行记录存储。
        """

        if self._task_execution_store is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=TASK_EXECUTION_STORE_NOT_READY_MESSAGE,
            )
        return self._task_execution_store

    def create_auth_identity_repository(
        self,
        session: PersistenceSession,
    ) -> AuthIdentityRepository:
        """
        创建鉴权身份仓储。
        """

        return AuthIdentityRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_refresh_token_repository(
        self,
        session: PersistenceSession,
    ) -> RefreshTokenRepository:
        """
        创建刷新令牌仓储。
        """

        return RefreshTokenRepositoryImpl(self._read_sqlalchemy_session(session))

    def _read_sqlalchemy_session(self, session: PersistenceSession) -> Session:
        """读取并校验 SQLAlchemy 会话实现。

        :param session: 核心层名义持久化会话。
        :type session: PersistenceSession
        :returns: SQLAlchemy 会话。
        :rtype: Session
        :raises TypeError: 当会话不是 SQLAlchemy 实现时抛出。
        """

        if not isinstance(session, Session):
            raise TypeError("当前持久化会话不是 SQLAlchemy 实现。")
        return session

    def create_admin_identity_repository(
        self,
        session: Session,
    ) -> AdminIdentityRepositoryImpl:
        """
        创建管理员身份仓储。

        :param session: 当前数据库会话，生命周期由工作单元控制。
        :type session: Session
        :returns: 管理员身份仓储实现。
        :rtype: AdminIdentityRepositoryImpl
        """

        return AdminIdentityRepositoryImpl(session)

    def get_cache_store(self) -> CacheStore:
        """
        获取缓存存储。
        """

        if self._cache_store is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=CACHE_STORE_NOT_READY_MESSAGE,
            )
        return self._cache_store

    def get_cache_service(self) -> CacheService:
        """
        获取缓存服务。
        """

        if self._cache_service is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=CACHE_SERVICE_NOT_READY_MESSAGE,
            )
        return self._cache_service

    def get_distributed_lock_provider(self) -> DistributedLockProvider:
        """
        获取分布式锁提供者。
        """

        if self._distributed_lock_provider is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=DISTRIBUTED_LOCK_NOT_READY_MESSAGE,
            )
        return self._distributed_lock_provider

    def get_key_management_service(self) -> KeyManagementService:
        """
        获取密钥管理服务。
        """

        if self._key_management_service is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=KEY_MANAGEMENT_NOT_READY_MESSAGE,
            )
        return self._key_management_service

    def get_sensitive_digest_service(self) -> SensitiveDigestService:
        """
        获取敏感摘要服务。
        """

        if self._sensitive_digest_service is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._sensitive_digest_service

    def get_token_binding_guard(self) -> TokenBindingGuard:
        """
        获取 Token-IP 绑定守卫。
        """

        if self._token_binding_guard is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._token_binding_guard

    def get_client_ip_resolver(self) -> ClientIpResolver:
        """
        获取客户端 IP 解析器。
        """

        if self._client_ip_resolver is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=CLIENT_IP_RESOLVER_NOT_READY_MESSAGE,
            )
        return self._client_ip_resolver

    def get_security_event_builder(self) -> SecurityEventBuilder:
        """
        获取安全事件构造器。
        """

        if self._security_event_builder is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._security_event_builder

    def get_risk_signal_guard(self) -> RiskSignalGuard:
        """
        获取风险信号守卫。
        """

        if self._risk_signal_guard is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._risk_signal_guard

    def get_security_protection_guard(self) -> SecurityProtectionGuard:
        """
        获取安全防护门面。
        """

        if self._security_protection_guard is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._security_protection_guard

    def get_ip_block_guard(self) -> IpBlockGuard:
        """
        获取 IP 封禁守卫。
        """

        if self._ip_block_guard is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._ip_block_guard

    def get_security_ip_block_runtime(self) -> IpBlockRuntimeDetail:
        """
        获取 IP 封禁运行时配置。
        """

        return self.read_runtime_bundle().settings.runtime.security.detail.protection.ip_block

    def get_outbound_url_safety_validator(self) -> OutboundUrlSafetyValidator:
        """
        获取出站 URL 安全校验器。
        """

        if self._outbound_url_safety_validator is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SECURITY_PROTECTION_NOT_READY_MESSAGE,
            )
        return self._outbound_url_safety_validator

    def get_telemetry_bridge(self) -> FastApiOtelBridge:
        """
        获取遥测桥接器。
        """

        return self._telemetry_bridge

    def get_log_event_builder(self) -> LogEventBuilder:
        """
        获取日志事件构造器。
        """

        return self._logging_accessor.log_event_builder

    def get_structured_log_handler(self) -> StructuredLogHandler:
        """
        获取结构化日志处理器。
        """

        if self._logging_accessor.structured_log_handler is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=LOGGER_RESOURCE_NOT_READY_MESSAGE,
            )
        return self._logging_accessor.structured_log_handler

    def get_request_execution_bridge(self) -> RequestExecutionBridge:
        """
        获取请求执行桥接器。
        """

        http_accessor = self.read_runtime_bundle().http_accessor
        if http_accessor.resource_set is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=REQUEST_EXECUTION_BRIDGE_NOT_READY_MESSAGE,
            )
        return http_accessor.resource_set.request_execution_bridge

    def get_async_http_client(self) -> SharedAsyncHttpClient:
        """
        获取异步 HTTP 客户端。
        """

        http_accessor = self.read_runtime_bundle().http_accessor
        if (
            http_accessor.resource_set is None
            or http_accessor.resource_set.async_http_client is None
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=ASYNC_HTTP_CLIENT_NOT_READY_MESSAGE,
            )
        return http_accessor.resource_set.async_http_client

    def get_http_client(self) -> SharedHttpClient:
        """
        获取同步 HTTP 客户端。
        """

        http_accessor = self.read_runtime_bundle().http_accessor
        if http_accessor.resource_set is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=SYNC_HTTP_CLIENT_NOT_READY_MESSAGE,
            )
        return http_accessor.resource_set.http_client
