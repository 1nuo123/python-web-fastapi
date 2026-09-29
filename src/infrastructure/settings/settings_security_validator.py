"""
配置安全校验器。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from src.core.cache_contract.cache_runtime_contract import CacheBackend
from src.core.http_contract.security_runtime_contract import (
    TRUSTED_LOOPBACK_IPV4_CIDR,
    TRUSTED_LOOPBACK_IPV6_CIDR,
    DevelopmentSecurityRuntimeDetail,
    ProductionSecurityRuntimeDetail,
)
from src.core.stream_contract.stream_runtime_contract import RedisStreamRuntimeDetail
from src.core.task_contract.task_registration_contract import FunboostTaskRegistrationDetail
from src.core.task_contract.task_runtime_contract import (
    FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND,
    FUNBOOST_TASK_BACKEND_KIND,
    LOCAL_TASK_BACKEND_KIND,
    FunboostTaskBackendDetail,
    LocalTaskBackendDetail,
    RabbitMqMessageBackendDetail,
)
from src.infrastructure.settings.application_settings import (
    CORS_WILDCARD,
    AppEnvironment,
    ApplicationSettings,
)

JWT_SECRET_MINIMUM_LENGTH = 32
DANGEROUS_JWT_SECRET_FRAGMENTS = (
    "dev-secret",
    "change-me",
    "test-secret",
    "local-dev",
)
PRODUCTION_BOOTSTRAP_ADMIN_ENABLED_MESSAGE = (
    "生产环境禁止长期启用 bootstrap admin，请先完成一次性初始化后关闭。"
)
PRODUCTION_CORS_WILDCARD_ORIGIN_FORBIDDEN_MESSAGE = "生产环境 CORS 允许源禁止使用通配符。"
PRODUCTION_MEMORY_AUTH_THROTTLE_MESSAGE = "生产认证节流必须使用 Redis 或外部缓存。"
PRODUCTION_JWT_SECRET_REQUIRED_MESSAGE = "生产环境必须通过 JWT_SECRET 注入 JWT 密钥。"
PRODUCTION_JWT_SECRET_WEAK_MESSAGE = "生产环境 JWT_SECRET 不允许使用弱密钥或示例密钥。"
PRODUCTION_EXTERNAL_JWT_SECRET_FLAG_REQUIRED_MESSAGE = "生产环境必须显式要求外部 JWT 密钥。"
PRODUCTION_DISTRIBUTED_AUTH_THROTTLE_FLAG_REQUIRED_MESSAGE = "生产环境必须显式要求分布式鉴权节流。"
PRODUCTION_DATABASE_URL_REQUIRED_MESSAGE = "生产环境必须通过 DATABASE_URL 注入数据库连接串。"
PRODUCTION_REDIS_URL_REQUIRED_MESSAGE = "生产环境必须通过 REDIS_URL 注入 Redis 连接串。"
PRODUCTION_REDIS_URL_PASSWORD_REQUIRED_MESSAGE = "生产环境 REDIS_URL 必须包含认证密码。"
PRODUCTION_RABBITMQ_URL_REQUIRED_MESSAGE = "生产环境必须通过 RABBITMQ_URL 注入 RabbitMQ 连接串。"
PRODUCTION_RABBITMQ_URL_CREDENTIAL_REQUIRED_MESSAGE = (
    "生产环境 RABBITMQ_URL 必须包含专用账号和密码。"
)
PRODUCTION_RABBITMQ_GUEST_FORBIDDEN_MESSAGE = "生产环境 RabbitMQ 禁止使用 guest/guest。"
RABBITMQ_GUEST_USERNAME = "guest"
RABBITMQ_GUEST_PASSWORD = "guest"
PRODUCTION_LOOPBACK_TRUSTED_PROXY_FORBIDDEN_MESSAGE = (
    "生产环境 trusted_proxy_cidr_blocks 禁止使用环回代理 CIDR。"
)
PRODUCTION_OUTBOUND_URL_SAFETY_DISABLED_MESSAGE = "生产环境必须启用出站 URL 安全策略。"
PRODUCTION_OUTBOUND_NON_GLOBAL_DENY_REQUIRED_MESSAGE = (
    "生产环境出站 URL 安全策略必须拒绝非 global 地址。"
)
PRODUCTION_OUTBOUND_METADATA_DENY_REQUIRED_MESSAGE = (
    "生产环境出站 URL 安全策略必须拒绝 metadata 地址。"
)
PRODUCTION_OUTBOUND_HOST_ALLOWLIST_REQUIRED_MESSAGE = (
    "生产环境出站 URL 安全策略必须启用目的域名允许清单。"
)
PRODUCTION_STREAM_WILDCARD_ORIGIN_FORBIDDEN_MESSAGE = (
    "生产环境流式 allowed_origins 禁止使用通配符。"
)
PRODUCTION_STREAM_REDIS_REQUIRED_MESSAGE = "生产环境流式恢复必须使用 Redis 后端。"
PRODUCTION_STREAM_TICKET_REQUIRED_MESSAGE = "生产环境浏览器流式连接必须使用单次票据。"
LOOPBACK_TRUSTED_PROXY_CIDR_BLOCKS = frozenset(
    {
        TRUSTED_LOOPBACK_IPV4_CIDR,
        TRUSTED_LOOPBACK_IPV6_CIDR,
    }
)


class SettingsSecurityValidator:
    """
    配置安全校验器。
    """

    def validate_production_environment(
        self,
        *,
        jwt_secret: str | None,
        database_url: str | None,
        redis_url: str | None,
        rabbitmq_url: str | None,
    ) -> None:
        """
        校验生产环境外部敏感配置。
        """

        self._validate_production_jwt_secret(jwt_secret)
        self._validate_production_external_runtime_secrets(
            database_url=database_url,
            redis_url=redis_url,
            rabbitmq_url=rabbitmq_url,
        )

    def validate_settings(self, settings: ApplicationSettings) -> None:
        """
        校验已经完成模型解析的应用配置。
        """

        self._validate_security_runtime_consistency(settings)
        self._validate_task_runtime_consistency(settings)

    def _validate_production_jwt_secret(self, jwt_secret: str | None) -> None:
        """
        校验生产 JWT 密钥。
        """

        if jwt_secret is None or jwt_secret.strip() == "":
            raise ValueError(PRODUCTION_JWT_SECRET_REQUIRED_MESSAGE)
        normalized_secret = jwt_secret.strip().lower()
        if len(jwt_secret.strip()) < JWT_SECRET_MINIMUM_LENGTH:
            raise ValueError(PRODUCTION_JWT_SECRET_WEAK_MESSAGE)
        if any(
            dangerous_fragment in normalized_secret
            for dangerous_fragment in DANGEROUS_JWT_SECRET_FRAGMENTS
        ):
            raise ValueError(PRODUCTION_JWT_SECRET_WEAK_MESSAGE)

    def _validate_production_external_runtime_secrets(
        self,
        *,
        database_url: str | None,
        redis_url: str | None,
        rabbitmq_url: str | None,
    ) -> None:
        """
        校验生产外部运行时敏感配置注入。
        """

        self._validate_required_secret(
            secret_value=database_url,
            required_message=PRODUCTION_DATABASE_URL_REQUIRED_MESSAGE,
        )
        self._validate_required_secret(
            secret_value=redis_url,
            required_message=PRODUCTION_REDIS_URL_REQUIRED_MESSAGE,
        )
        self._validate_required_secret(
            secret_value=rabbitmq_url,
            required_message=PRODUCTION_RABBITMQ_URL_REQUIRED_MESSAGE,
        )
        self._validate_production_redis_url(redis_url=redis_url)
        self._validate_production_rabbitmq_url(rabbitmq_url=rabbitmq_url)

    def _validate_required_secret(
        self,
        *,
        secret_value: str | None,
        required_message: str,
    ) -> None:
        """
        校验生产必填敏感值。
        """

        if secret_value is None or secret_value.strip() == "":
            raise ValueError(required_message)

    def _validate_production_redis_url(self, *, redis_url: str | None) -> None:
        """
        校验生产 Redis 连接串认证信息。
        """

        if redis_url is None:
            raise ValueError(PRODUCTION_REDIS_URL_REQUIRED_MESSAGE)
        parsed_url = urlsplit(redis_url)
        if parsed_url.password is None or parsed_url.password.strip() == "":
            raise ValueError(PRODUCTION_REDIS_URL_PASSWORD_REQUIRED_MESSAGE)

    def _validate_production_rabbitmq_url(self, *, rabbitmq_url: str | None) -> None:
        """
        校验生产 RabbitMQ 连接串认证信息。
        """

        if rabbitmq_url is None:
            raise ValueError(PRODUCTION_RABBITMQ_URL_REQUIRED_MESSAGE)
        parsed_url = urlsplit(rabbitmq_url)
        username = parsed_url.username
        password = parsed_url.password
        if username is None or password is None:
            raise ValueError(PRODUCTION_RABBITMQ_URL_CREDENTIAL_REQUIRED_MESSAGE)
        if username == RABBITMQ_GUEST_USERNAME and password == RABBITMQ_GUEST_PASSWORD:
            raise ValueError(PRODUCTION_RABBITMQ_GUEST_FORBIDDEN_MESSAGE)

    def _validate_security_runtime_consistency(
        self,
        settings: ApplicationSettings,
    ) -> None:
        """
        校验安全运行时一致性。
        """

        security_detail = settings.runtime.security.detail
        if settings.app.environment == AppEnvironment.PRODUCTION:
            if not isinstance(security_detail, ProductionSecurityRuntimeDetail):
                raise ValueError("生产环境必须使用 production_security 安全运行时扩展。")
            if settings.app.enable_openapi or security_detail.expose_openapi:
                raise ValueError("生产环境必须关闭 OpenAPI 公开入口。")
            if security_detail.expose_system_info:
                raise ValueError("生产环境禁止匿名公开系统信息。")
            if settings.runtime.cache.backend == CacheBackend.MEMORY:
                raise ValueError(PRODUCTION_MEMORY_AUTH_THROTTLE_MESSAGE)
            if not security_detail.require_external_jwt_secret:
                raise ValueError(PRODUCTION_EXTERNAL_JWT_SECRET_FLAG_REQUIRED_MESSAGE)
            if not security_detail.require_distributed_auth_throttle:
                raise ValueError(PRODUCTION_DISTRIBUTED_AUTH_THROTTLE_FLAG_REQUIRED_MESSAGE)
            if settings.modules.auth.bootstrap_admin.enabled:
                raise ValueError(PRODUCTION_BOOTSTRAP_ADMIN_ENABLED_MESSAGE)
            if (
                settings.runtime.web.cors.enabled
                and CORS_WILDCARD in settings.runtime.web.cors.allow_origins
            ):
                raise ValueError(PRODUCTION_CORS_WILDCARD_ORIGIN_FORBIDDEN_MESSAGE)
            self._validate_production_client_ip_trusted_proxies(security_detail)
            self._validate_production_outbound_url_safety(security_detail)
            self._validate_production_stream_runtime(settings)
        elif not isinstance(security_detail, DevelopmentSecurityRuntimeDetail):
            raise ValueError("非生产环境必须使用 development_security 安全运行时扩展。")

    def _validate_production_client_ip_trusted_proxies(
        self,
        security_detail: ProductionSecurityRuntimeDetail,
    ) -> None:
        """
        校验生产环境可信代理 CIDR 不得保留本机开发默认值。
        """

        trusted_proxy_cidr_blocks = security_detail.protection.client_ip.trusted_proxy_cidr_blocks
        if any(
            cidr_block in LOOPBACK_TRUSTED_PROXY_CIDR_BLOCKS
            for cidr_block in trusted_proxy_cidr_blocks
        ):
            raise ValueError(PRODUCTION_LOOPBACK_TRUSTED_PROXY_FORBIDDEN_MESSAGE)

    def _validate_production_stream_runtime(self, settings: ApplicationSettings) -> None:
        """校验生产流式运行时安全组合。

        :param settings: 已完成模型解析的应用配置。
        :type settings: ApplicationSettings
        :raises ValueError: 生产流式配置不满足安全约束时抛出。
        """

        stream_runtime = settings.runtime.stream
        if not stream_runtime.header.enabled:
            return
        if not isinstance(stream_runtime.detail, RedisStreamRuntimeDetail):
            raise ValueError(PRODUCTION_STREAM_REDIS_REQUIRED_MESSAGE)
        if CORS_WILDCARD in stream_runtime.detail.allowed_origins:
            raise ValueError(PRODUCTION_STREAM_WILDCARD_ORIGIN_FORBIDDEN_MESSAGE)
        if not stream_runtime.detail.require_browser_ticket:
            raise ValueError(PRODUCTION_STREAM_TICKET_REQUIRED_MESSAGE)

    def _validate_production_outbound_url_safety(
        self,
        security_detail: ProductionSecurityRuntimeDetail,
    ) -> None:
        """
        校验生产环境出站 URL 安全策略。
        """

        outbound_url_safety = security_detail.protection.outbound_url_safety
        if not outbound_url_safety.enabled:
            raise ValueError(PRODUCTION_OUTBOUND_URL_SAFETY_DISABLED_MESSAGE)
        if not outbound_url_safety.deny_private_networks:
            raise ValueError(PRODUCTION_OUTBOUND_NON_GLOBAL_DENY_REQUIRED_MESSAGE)
        if not outbound_url_safety.deny_metadata_address:
            raise ValueError(PRODUCTION_OUTBOUND_METADATA_DENY_REQUIRED_MESSAGE)
        if not outbound_url_safety.enforce_allowed_hostnames:
            raise ValueError(PRODUCTION_OUTBOUND_HOST_ALLOWLIST_REQUIRED_MESSAGE)

    def _validate_task_runtime_consistency(
        self,
        settings: ApplicationSettings,
    ) -> None:
        """
        校验任务注册、任务运行时与消息运行时的一致性。
        """

        default_job_kind = settings.modules.task.default_job_kind
        if default_job_kind == "":
            raise ValueError("modules.task.default_job_kind 不能为空字符串。")
        if len(settings.modules.task.registrations) == 0:
            raise ValueError("modules.task.registrations 不能为空。")
        registration_by_job_kind = {
            registration.header.job_kind: registration
            for registration in settings.modules.task.registrations
        }
        default_registration = registration_by_job_kind.get(default_job_kind)
        if default_registration is None:
            raise ValueError("modules.task.default_job_kind 必须存在于 registrations 中。")
        if settings.app.environment == AppEnvironment.PRODUCTION:
            if not default_registration.header.enabled:
                raise ValueError("modules.task.default_job_kind 对应任务必须启用。")
            if default_registration.header.backend != settings.runtime.task.backend:
                raise ValueError(
                    "modules.task.default_job_kind 对应任务 backend 必须与 runtime.task.backend 一致。"
                )
        if settings.runtime.task.backend.value == FUNBOOST_TASK_BACKEND_KIND and not isinstance(
            settings.runtime.message.backend_detail,
            RabbitMqMessageBackendDetail,
        ):
            raise ValueError(
                "启用 funboost 任务后端时，runtime.message.backend_detail 必须为 RabbitMQ 配置。"
            )
        if settings.runtime.task.backend.value == FUNBOOST_TASK_BACKEND_KIND:
            task_backend_detail = settings.runtime.task.backend_detail
            message_backend_detail = settings.runtime.message.backend_detail
            if not isinstance(task_backend_detail, FunboostTaskBackendDetail):
                raise ValueError("启用 funboost 任务后端时，任务扩展配置类型不正确。")
            if not isinstance(message_backend_detail, RabbitMqMessageBackendDetail):
                raise ValueError("启用 funboost 任务后端时，消息扩展配置类型不正确。")
            if not message_backend_detail.task_message_persistent:
                raise ValueError("启用 funboost 任务后端时必须开启 RabbitMQ 消息持久化。")
            if not message_backend_detail.publisher_confirm_enabled:
                raise ValueError("启用 funboost 任务后端时必须开启 RabbitMQ 发布确认。")
            if (
                message_backend_detail.dead_letter_exchange_name
                == message_backend_detail.task_exchange_name
            ):
                raise ValueError("RabbitMQ 死信交换机不能与任务交换机同名。")
            if (
                task_backend_detail.broker_kind.value
                != FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND
            ):
                raise ValueError(
                    "启用 funboost 任务后端时，runtime.task.backend_detail.broker_kind 必须为 RABBITMQ_COMPLEX_ROUTING。"
                )
        if settings.runtime.task.backend.value == LOCAL_TASK_BACKEND_KIND:
            task_detail = settings.runtime.task.backend_detail
            if not isinstance(task_detail, LocalTaskBackendDetail):
                raise ValueError("启用 local 任务后端时，任务扩展配置类型不正确。")
            if not task_detail.inline_execute_enabled:
                raise ValueError(
                    "local 任务后端仅支持 inline 执行；inline_execute_enabled 必须为 true。"
                )
        for registration in settings.modules.task.registrations:
            if not registration.header.enabled:
                continue
            if registration.header.backend != settings.runtime.task.backend:
                continue
            if isinstance(registration.detail, FunboostTaskRegistrationDetail):
                if not isinstance(
                    settings.runtime.message.backend_detail,
                    RabbitMqMessageBackendDetail,
                ):
                    raise ValueError(
                        "启用 funboost 注册任务时，runtime.message.backend_detail 必须为 RabbitMQ 配置。"
                    )
                if (
                    registration.detail.exchange_name
                    != settings.runtime.message.backend_detail.task_exchange_name
                ):
                    raise ValueError(
                        "funboost 任务注册的 exchange_name 必须与 runtime.message.backend_detail.task_exchange_name 一致。"
                    )
                if (
                    registration.detail.broker_kind.value
                    != FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND
                ):
                    raise ValueError(
                        "funboost 任务注册的 broker_kind 必须为 RABBITMQ_COMPLEX_ROUTING。"
                    )
