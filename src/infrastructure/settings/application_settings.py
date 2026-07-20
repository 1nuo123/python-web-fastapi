"""
应用配置加载器基础设施模块。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    model_validator,
)

from src.core.auth_contract.bootstrap_role_binding_contract import (
    BootstrapRoleBinding,
)
from src.core.cache_contract.cache_runtime_contract import CacheRuntimeSettings
from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockRuntimeEnvelope,
)
from src.core.http_contract.outbound_http_client_contract import (
    OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND,
    OutboundHttpClientEnvelope,
)
from src.core.http_contract.request_execution_contract import (
    REQUEST_EXECUTION_ENVELOPE_KIND,
    RequestExecutionEnvelope,
)
from src.core.http_contract.security_runtime_contract import (
    SecurityRuntimeEnvelope,
)
from src.core.key_management_contract.key_management_contract import (
    KeyManagementRuntimeEnvelope,
)
from src.core.logging_contract.log_runtime_contract import (
    LoggingRuntimeSettings,
)
from src.core.observability_contract.metrics_runtime_contract import (
    MetricsRuntimeEnvelope,
)
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
    TaskRegistrationEnvelope,
)
from src.core.task_contract.task_runtime_contract import (
    RETRY_LIMIT_MINIMUM,
    MessageBackend,
    MessageBackendDetailUnion,
    TaskBackend,
    TaskBackendDetailUnion,
)

SETTINGS_LOGGER_NAME = "fastapi_web_skeleton.settings"
APP_ENVIRONMENT_VARIABLE = "APP_ENV"
DATABASE_URL_ENVIRONMENT_VARIABLE = "DATABASE_URL"
REDIS_URL_ENVIRONMENT_VARIABLE = "REDIS_URL"
RABBITMQ_URL_ENVIRONMENT_VARIABLE = "RABBITMQ_URL"
JWT_SECRET_ENVIRONMENT_VARIABLE = "JWT_SECRET"
AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE = "AUTH_BOOTSTRAP_ADMIN_PASSWORD"
RUNTIME_WEB_API_PREFIX_ENVIRONMENT_VARIABLE = "RUNTIME_WEB_API_PREFIX"
APP_SECTION_KEY: Final = "app"
MODULE_SECTION_KEY: Final = "module"
RUNTIME_SECTION_KEY: Final = "runtime"
SYSTEM_MODULE_SECTION_KEY: Final = "system_module"
AUTH_MODULE_SECTION_KEY: Final = "auth_module"
TASK_MODULE_SECTION_KEY: Final = "task_module"
WEB_RUNTIME_SECTION_KEY: Final = "web"
AUTH_RUNTIME_SECTION_KEY: Final = "auth"
DATABASE_RUNTIME_SECTION_KEY: Final = "database"
CACHE_RUNTIME_SECTION_KEY: Final = "cache"
MESSAGE_RUNTIME_SECTION_KEY: Final = "message"
TASK_RUNTIME_SECTION_KEY: Final = "task"
OTEL_RUNTIME_SECTION_KEY: Final = "otel"
METRICS_RUNTIME_SECTION_KEY: Final = "metrics"
LOGGING_RUNTIME_SECTION_KEY: Final = "logging"
METRICS_RUNTIME_DIRECTORY_NAME: Final = "metrics_runtime"
OTEL_RUNTIME_DIRECTORY_NAME: Final = "otel_runtime"
LOGGING_RUNTIME_DIRECTORY_NAME: Final = "logging_runtime"
SECURITY_RUNTIME_SECTION_KEY: Final = "security"
DISTRIBUTED_LOCK_RUNTIME_SECTION_KEY: Final = "distributed_lock"
KEY_MANAGEMENT_RUNTIME_SECTION_KEY: Final = "key_management"
DISTRIBUTED_LOCK_RUNTIME_DIRECTORY_NAME: Final = "distributed_lock_runtime"
KEY_MANAGEMENT_RUNTIME_DIRECTORY_NAME: Final = "key_management_runtime"
BOOTSTRAP_ADMIN_SECTION_KEY: Final = "bootstrap_admin"
PASSWORD_PLAIN_FIELD_KEY: Final = "password_plain"
API_PREFIX_FIELD_KEY: Final = "api_prefix"
ENTRY_PROJECT_NAME_FIELD_KEY: Final = "entry_project_name"
ENTRY_LOG_PATH_FIELD_KEY: Final = "entry_log_path"
ROLE_BINDINGS_FIELD_KEY: Final = "role_bindings"
ROLE_KEY_FIELD_KEY: Final = "role_key"
SCOPE_CODES_FIELD_KEY: Final = "scope_codes"
BACKEND_FIELD_KEY: Final = "backend"
BACKEND_DETAIL_FIELD_KEY: Final = "backend_detail"
REDIS_URL_FIELD_KEY: Final = "redis_url"
RABBITMQ_URL_FIELD_KEY: Final = "rabbitmq_url"
POSITIVE_INTEGER_MINIMUM = 1
ROOT_API_PREFIX = ""
URL_PATH_SEPARATOR = "/"
QUEUE_NAME_FIELD_NAME = "queue_name"
JOB_KIND_FIELD_NAME = "job_kind"
DEFAULT_JOB_KIND_FIELD_NAME = "default_job_kind"
CORS_WILDCARD = "*"
CORS_ALLOW_ORIGINS_EMPTY_MESSAGE = "runtime.web.cors.allow_origins 启用时不能为空。"
CORS_ALLOW_METHODS_EMPTY_MESSAGE = "runtime.web.cors.allow_methods 启用时不能为空。"
CORS_ALLOW_HEADERS_EMPTY_MESSAGE = "runtime.web.cors.allow_headers 启用时不能为空。"
POSTGRESQL_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
DATABASE_SCHEMA_NAME_INVALID_MESSAGE = "database.schema 必须是单个合法 PostgreSQL 标识符。"


class AppEnvironment(StrEnum):
    """
    应用环境枚举，用于约束可选取值。

    :cvar DEVELOPMENT: ``DEVELOPMENT`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'development'`。取值语义：用于承载当前对象中的业务状态。
    :vartype DEVELOPMENT: str
    :cvar TEST: ``TEST`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'test'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TEST: str
    :cvar PRODUCTION: ``PRODUCTION`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'production'`。取值语义：用于承载当前对象中的业务状态。
    :vartype PRODUCTION: str
    """

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class DatabaseBackend(StrEnum):
    """
    数据库后端枚举，用于约束可选取值。

    :cvar POSTGRESQL: ``POSTGRESQL`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'postgresql'`。取值语义：用于承载当前对象中的业务状态。
    :vartype POSTGRESQL: str
    """

    POSTGRESQL = "postgresql"


class PasswordHashAlgorithm(StrEnum):
    """
    密码哈希算法枚举，用于约束可选取值。

    :cvar ARGON2: ``ARGON2`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'argon2'`。取值语义：用于承载当前对象中的业务状态。
    :vartype ARGON2: str
    """

    ARGON2 = "argon2"


class ApplicationModuleSwitchSettings(BaseModel):
    """
    应用模块开关Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar enabled: 功能是否启用。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：使用 Web manifest 的模块名作为启用键。
    :vartype enabled: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_enabled_modules(self) -> ApplicationModuleSwitchSettings:
        """
        校验启用模块集合。

        :returns: 返回当前操作结果。
        :rtype: 'ApplicationModuleSwitchSettings'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if len(set(self.enabled)) != len(self.enabled):
            raise ValueError("app.modules.enabled 不允许重复。")
        if any(module_name.strip() == "" for module_name in self.enabled):
            raise ValueError("app.modules.enabled 不允许包含空模块名。")
        return self


class ApplicationReloadPolicySettings(BaseModel):
    """
    应用重载策略Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar hot_reload_allowed: ``hot_reload_allowed`` 字段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于按顺序承载多个同类值。
    :vartype hot_reload_allowed: list[str]
    :ivar restart_required: ``restart_required`` 字段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于按顺序承载多个同类值。
    :vartype restart_required: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    hot_reload_allowed: list[str] = Field(default_factory=list)
    restart_required: list[str] = Field(default_factory=list)


class ApplicationMetaSettings(BaseModel):
    """
    应用元信息Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar name: ``name`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype name: str
    :ivar version: ``version`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype version: str
    :ivar environment: ``environment`` 字段。约束：需符合 ``AppEnvironment`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype environment: AppEnvironment
    :ivar enable_openapi: ``enable_openapi`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enable_openapi: bool
    :ivar modules: ``modules`` 字段。约束：需符合 ``ApplicationModuleSwitchSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype modules: ApplicationModuleSwitchSettings
    :ivar reload: ``reload`` 字段。约束：需符合 ``ApplicationReloadPolicySettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype reload: ApplicationReloadPolicySettings
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    environment: AppEnvironment
    enable_openapi: bool
    modules: ApplicationModuleSwitchSettings
    reload: ApplicationReloadPolicySettings


class SystemModuleSettings(BaseModel):
    """
    系统模块Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar ready_probe_enabled: ``ready_probe_enabled`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype ready_probe_enabled: bool
    :ivar overview_title: ``overview_title`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype overview_title: str
    """

    model_config = ConfigDict(extra="forbid")

    ready_probe_enabled: bool
    overview_title: str


class BootstrapAdminSettings(BaseModel):
    """
    引导管理员Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar enabled: 功能是否启用。约束：需符合 ``bool`` 注解。默认值：`False`。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enabled: bool
    :ivar username: 登录用户名。约束：需符合 ``str | None`` 注解；允许为空值。默认值：`None`。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str | None
    :ivar password_plain: 明文密码。约束：需符合 ``SecretStr | None`` 注解；允许为空值。默认值：`None`。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_plain: SecretStr | None
    :ivar subject_id: 认证主体标识。约束：需符合 ``str | None`` 注解；允许为空值。默认值：`None`。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str | None
    :ivar role_bindings: ``role_bindings`` 字段。约束：需符合 ``list[BootstrapRoleBinding]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于描述角色标识或角色关联关系。
    :vartype role_bindings: list[BootstrapRoleBinding]
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    username: str | None = None
    password_plain: SecretStr | None = None
    subject_id: str | None = None
    role_bindings: list[BootstrapRoleBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_enabled_fields(self) -> BootstrapAdminSettings:
        """
        校验启用字段集合。

        :returns: 返回当前操作结果。
        :rtype: 'BootstrapAdminSettings'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if not self.enabled:
            return self
        required_string_fields = {
            "username": self.username,
            "subject_id": self.subject_id,
        }
        for field_name, field_value in required_string_fields.items():
            if field_value is None or field_value.strip() == "":
                raise ValueError(f"{field_name} 不能为空。")
        if self.password_plain is None or self.password_plain.get_secret_value().strip() == "":
            raise ValueError("password_plain 不能为空。")
        if not self.role_bindings:
            raise ValueError("role_bindings 不能为空。")
        role_keys = [role_binding.role_key.strip() for role_binding in self.role_bindings]
        if any(role_key == "" for role_key in role_keys):
            raise ValueError("role_bindings.role_key 不能为空。")
        if len(set(role_keys)) != len(role_keys):
            raise ValueError("role_bindings.role_key 不允许重复。")
        for role_binding in self.role_bindings:
            if not role_binding.scope_codes:
                raise ValueError("role_bindings.scope_codes 不能为空。")
            if any(scope_code.strip() == "" for scope_code in role_binding.scope_codes):
                raise ValueError("role_bindings.scope_codes 不能为空字符串。")
            if len(set(role_binding.scope_codes)) != len(role_binding.scope_codes):
                raise ValueError("role_bindings.scope_codes 不允许重复。")
        return self


class AuthModuleSettings(BaseModel):
    """
    鉴权模块Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar bootstrap_admin: ``bootstrap_admin`` 字段。约束：需符合 ``BootstrapAdminSettings`` 注解。默认值：由 ``BootstrapAdminSettings`` 动态生成。取值语义：用于承载当前对象中的业务状态。
    :vartype bootstrap_admin: BootstrapAdminSettings
    """

    model_config = ConfigDict(extra="forbid")

    bootstrap_admin: BootstrapAdminSettings = Field(default_factory=BootstrapAdminSettings)


class TaskModuleSettings(BaseModel):
    """
    任务模块Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar default_retry_limit: 默认重试次数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype default_retry_limit: int
    :ivar default_job_kind: 默认任务类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype default_job_kind: str
    """

    model_config = ConfigDict(extra="forbid")

    default_retry_limit: int
    default_job_kind: str
    registrations: list[TaskRegistrationEnvelope] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_task_module_contract(self) -> TaskModuleSettings:
        """
        校验任务模块配置。
        :returns: 当前模型实例。
        :rtype: TaskModuleSettings
        :raises ValueError: 当默认任务或注册清单不合法时抛出。
        """

        if self.default_retry_limit < RETRY_LIMIT_MINIMUM:
            raise ValueError("modules.task.default_retry_limit 不能小于 0。")
        if not self.registrations:
            raise ValueError("modules.task.registrations 不能为空。")
        registration_by_job_kind: dict[str, TaskRegistrationEnvelope] = {}
        funboost_queue_names: set[str] = set()
        for registration in self.registrations:
            current_job_kind = registration.header.job_kind
            if current_job_kind in registration_by_job_kind:
                raise ValueError("modules.task.registrations.job_kind 不允许重复。")
            registration_by_job_kind[current_job_kind] = registration
            if isinstance(registration.detail, FunboostTaskRegistrationDetail):
                current_queue_name = registration.detail.queue_name
                if current_queue_name in funboost_queue_names:
                    raise ValueError("modules.task.registrations.detail.queue_name 不允许重复。")
                funboost_queue_names.add(current_queue_name)
        if self.default_job_kind not in registration_by_job_kind:
            raise ValueError("modules.task.default_job_kind 必须存在于 registrations 中。")
        return self


class ModuleSettings(BaseModel):
    """
    模块Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar system: ``system`` 字段。约束：需符合 ``SystemModuleSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype system: SystemModuleSettings
    :ivar auth: ``auth`` 字段。约束：需符合 ``AuthModuleSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype auth: AuthModuleSettings
    :ivar task: ``task`` 字段。约束：需符合 ``TaskModuleSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype task: TaskModuleSettings
    """

    model_config = ConfigDict(extra="forbid")

    system: SystemModuleSettings
    auth: AuthModuleSettings
    task: TaskModuleSettings


class RuntimeCorsSettings(BaseModel):
    """
    CORS 运行时配置。

    :ivar enabled: 是否启用 CORS 中间件。
    :vartype enabled: bool
    :ivar allow_origins: 允许的来源列表。
    :vartype allow_origins: list[str]
    :ivar allow_methods: 允许的 HTTP 方法列表。
    :vartype allow_methods: list[str]
    :ivar allow_headers: 允许的请求头列表。
    :vartype allow_headers: list[str]
    :ivar allow_credentials: 是否允许携带凭证。
    :vartype allow_credentials: bool
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    allow_origins: list[str]
    allow_methods: list[str]
    allow_headers: list[str]
    allow_credentials: bool

    @model_validator(mode="after")
    def validate_enabled_policy(self) -> RuntimeCorsSettings:
        """
        校验启用时的 CORS 配置完整性。

        :returns: 当前 CORS 运行时配置。
        :rtype: RuntimeCorsSettings
        :raises ValueError: 当启用后缺少必要允许列表时抛出。
        """

        self.allow_origins = self._normalize_values(self.allow_origins)
        self.allow_methods = self._normalize_values(self.allow_methods)
        self.allow_headers = self._normalize_values(self.allow_headers)
        if not self.enabled:
            return self
        if len(self.allow_origins) == 0:
            raise ValueError(CORS_ALLOW_ORIGINS_EMPTY_MESSAGE)
        if len(self.allow_methods) == 0:
            raise ValueError(CORS_ALLOW_METHODS_EMPTY_MESSAGE)
        if len(self.allow_headers) == 0:
            raise ValueError(CORS_ALLOW_HEADERS_EMPTY_MESSAGE)
        return self

    def _normalize_values(self, values: list[str]) -> list[str]:
        """
        归一化 CORS 字符串列表。

        :param values: CORS 配置列表。
        :type values: list[str]
        :returns: 去除空白项后的配置列表。
        :rtype: list[str]
        """

        return [value.strip() for value in values if value.strip() != ""]


class WebRuntimeSettings(BaseModel):
    """
    Web运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar api_prefix: 接口统一前缀。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype api_prefix: str
    :ivar max_request_body_bytes: 请求体最大字节数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype max_request_body_bytes: int
    :ivar enable_access_log: 是否启用访问日志。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enable_access_log: bool
    :ivar enable_security_headers: 是否启用安全响应头。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enable_security_headers: bool
    :ivar include_middleware_trace_header: 是否输出中间件轨迹头。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype include_middleware_trace_header: bool
    :ivar request_execution: 请求执行策略信封。约束：需符合 ``RequestExecutionEnvelope`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype request_execution: RequestExecutionEnvelope
    :ivar outbound_http_client: 外部 HTTP 客户端信封。约束：需符合 ``OutboundHttpClientEnvelope`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype outbound_http_client: OutboundHttpClientEnvelope
    :ivar cors: CORS 运行时配置。
    :vartype cors: RuntimeCorsSettings
    """

    model_config = ConfigDict(extra="forbid")

    api_prefix: str
    max_request_body_bytes: int
    enable_access_log: bool
    enable_security_headers: bool
    include_middleware_trace_header: bool
    cors: RuntimeCorsSettings
    request_execution: RequestExecutionEnvelope
    outbound_http_client: OutboundHttpClientEnvelope

    @model_validator(mode="after")
    def validate_positive_boundary(self) -> WebRuntimeSettings:
        """
        校验正值边界。

        :returns: 返回当前操作结果。
        :rtype: 'WebRuntimeSettings'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if self.max_request_body_bytes < POSITIVE_INTEGER_MINIMUM:
            raise ValueError("runtime.web.max_request_body_bytes 必须大于 0。")
        normalized_api_prefix = self.api_prefix.strip()
        if normalized_api_prefix == URL_PATH_SEPARATOR:
            self.api_prefix = ROOT_API_PREFIX
        elif normalized_api_prefix == ROOT_API_PREFIX:
            self.api_prefix = ROOT_API_PREFIX
        else:
            if not normalized_api_prefix.startswith(URL_PATH_SEPARATOR):
                raise ValueError("runtime.web.api_prefix 必须为空或以 / 开头。")
            normalized_api_prefix = normalized_api_prefix.rstrip(URL_PATH_SEPARATOR)
            self.api_prefix = normalized_api_prefix or ROOT_API_PREFIX
        if self.request_execution.envelope_kind != REQUEST_EXECUTION_ENVELOPE_KIND:
            raise ValueError("runtime.web.request_execution.envelope_kind 不正确。")
        if self.outbound_http_client.envelope_kind != OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND:
            raise ValueError("runtime.web.outbound_http_client.envelope_kind 不正确。")
        return self


class SecurityRuntimeSettings(SecurityRuntimeEnvelope):
    """
    安全运行时Pydantic 模型，用于承载并校验安全公开面配置。
    """


class AuthRuntimeSettings(BaseModel):
    """
    鉴权运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar jwt_secret: JWT 签名密钥。约束：需符合 ``SecretStr`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的秘密状态。
    :vartype jwt_secret: SecretStr
    :ivar jwt_algorithm: JWT 签名算法。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype jwt_algorithm: str
    :ivar access_token_expires_in_seconds: 访问令牌有效期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype access_token_expires_in_seconds: int
    :ivar refresh_token_expires_in_seconds: 刷新令牌有效期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype refresh_token_expires_in_seconds: int
    :ivar issuer: JWT 签发方。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype issuer: str
    :ivar audience: JWT 受众。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype audience: str
    :ivar password_hash_algorithm: ``password_hash_algorithm`` 字段。约束：需符合 ``PasswordHashAlgorithm`` 注解。默认值：无，必须显式提供。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_hash_algorithm: PasswordHashAlgorithm
    :ivar refresh_token_rotation_enabled: 是否启用刷新令牌轮换。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token_rotation_enabled: bool
    :ivar issue_access_token_failure_limit: 访问令牌签发失败次数阈值。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype issue_access_token_failure_limit: int
    :ivar issue_access_token_failure_window_seconds: 访问令牌签发失败统计窗口秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype issue_access_token_failure_window_seconds: int
    :ivar refresh_access_token_failure_limit: 刷新令牌失败次数阈值。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_access_token_failure_limit: int
    :ivar refresh_access_token_failure_window_seconds: 刷新令牌失败统计窗口秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype refresh_access_token_failure_window_seconds: int
    :ivar throttle_lock_seconds: 节流锁定秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype throttle_lock_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    jwt_secret: SecretStr
    jwt_algorithm: str
    access_token_expires_in_seconds: int
    refresh_token_expires_in_seconds: int
    issuer: str
    audience: str
    password_hash_algorithm: PasswordHashAlgorithm
    refresh_token_rotation_enabled: bool
    issue_access_token_failure_limit: int
    issue_access_token_failure_window_seconds: int
    refresh_access_token_failure_limit: int
    refresh_access_token_failure_window_seconds: int
    throttle_lock_seconds: int

    @model_validator(mode="after")
    def validate_rotation_policy(self) -> AuthRuntimeSettings:
        """
        校验轮换策略。

        :returns: 返回当前操作结果。
        :rtype: 'AuthRuntimeSettings'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        positive_fields = {
            "runtime.auth.access_token_expires_in_seconds": self.access_token_expires_in_seconds,
            "runtime.auth.refresh_token_expires_in_seconds": self.refresh_token_expires_in_seconds,
            "runtime.auth.issue_access_token_failure_limit": self.issue_access_token_failure_limit,
            "runtime.auth.issue_access_token_failure_window_seconds": self.issue_access_token_failure_window_seconds,
            "runtime.auth.refresh_access_token_failure_limit": self.refresh_access_token_failure_limit,
            "runtime.auth.refresh_access_token_failure_window_seconds": self.refresh_access_token_failure_window_seconds,
            "runtime.auth.throttle_lock_seconds": self.throttle_lock_seconds,
        }
        for field_name, field_value in positive_fields.items():
            if field_value < POSITIVE_INTEGER_MINIMUM:
                raise ValueError(f"{field_name} 必须大于 0。")
        if not self.refresh_token_rotation_enabled:
            raise ValueError("当前设计要求 refresh_token_rotation_enabled 必须为 true。")
        return self


class DatabaseRuntimeSettings(BaseModel):
    """
    数据库运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid', populate_by_name=True)`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar backend: 后端类型。约束：需符合 ``DatabaseBackend`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: DatabaseBackend
    :ivar url: 数据库连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于连接外部资源或数据库。
    :vartype url: str
    :ivar schema_name: ``schema_name`` 字段。约束：需符合 ``str`` 注解；外部别名为 ``'schema'``。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_name: str
    :ivar echo: 是否输出 SQL 调试日志。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype echo: bool
    :ivar pool_size: 数据库连接池大小。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype pool_size: int
    :ivar max_overflow: 数据库连接池最大溢出连接数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype max_overflow: int
    :ivar pool_recycle_seconds: 数据库连接回收周期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype pool_recycle_seconds: int
    :ivar connect_timeout_seconds: 数据库连接超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype connect_timeout_seconds: int
    :ivar auto_upgrade_on_startup: 启动时是否自动执行数据库升级。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype auto_upgrade_on_startup: bool
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    backend: DatabaseBackend
    url: str
    schema_name: str = Field(alias="schema")
    echo: bool
    pool_size: int
    max_overflow: int
    pool_recycle_seconds: int
    connect_timeout_seconds: int
    auto_upgrade_on_startup: bool

    @model_validator(mode="after")
    def validate_postgresql_backend(self) -> DatabaseRuntimeSettings:
        """
        校验PostgreSQL后端。

        :returns: 返回当前操作结果。
        :rtype: 'DatabaseRuntimeSettings'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        positive_fields = {
            "runtime.database.pool_size": self.pool_size,
            "runtime.database.max_overflow": self.max_overflow,
            "runtime.database.pool_recycle_seconds": self.pool_recycle_seconds,
            "runtime.database.connect_timeout_seconds": self.connect_timeout_seconds,
        }
        for field_name, field_value in positive_fields.items():
            if field_value < POSITIVE_INTEGER_MINIMUM:
                raise ValueError(f"{field_name} 必须大于 0。")
        if self.backend != DatabaseBackend.POSTGRESQL:
            raise ValueError("当前设计仅支持 PostgreSQL 后端。")
        schema_name = self.schema_name.strip()
        if schema_name == "":
            raise ValueError("database.schema 不能为空。")
        if POSTGRESQL_SCHEMA_NAME_PATTERN.fullmatch(schema_name) is None:
            raise ValueError(DATABASE_SCHEMA_NAME_INVALID_MESSAGE)
        self.schema_name = schema_name
        return self


class MessageRuntimeSettings(BaseModel):
    """
    消息运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar backend: 后端类型。约束：需符合 ``MessageBackend`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: MessageBackend
    :ivar rabbitmq_url: RabbitMQ 连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于连接外部资源或数据库。
    :vartype rabbitmq_url: str
    """

    model_config = ConfigDict(extra="forbid")

    backend: MessageBackend
    backend_detail: MessageBackendDetailUnion

    @model_validator(mode="after")
    def validate_message_runtime_contract(self) -> MessageRuntimeSettings:
        """
        校验消息运行时配置。
        :returns: 当前模型实例。
        :rtype: MessageRuntimeSettings
        :raises ValueError: 当外层与内层不一致时抛出。
        """

        if self.backend.value != self.backend_detail.kind:
            raise ValueError(
                "runtime.message.backend 必须与 runtime.message.backend_detail.kind 一致。"
            )
        return self


class TaskRuntimeSettings(BaseModel):
    """
    任务运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar backend: 后端类型。约束：需符合 ``TaskBackend`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: TaskBackend
    :ivar worker_enabled: 任务工作器是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype worker_enabled: bool
    :ivar funboost_queue_name: Funboost 队列名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype funboost_queue_name: str
    """

    model_config = ConfigDict(extra="forbid")

    backend: TaskBackend
    worker_enabled: bool
    backend_detail: TaskBackendDetailUnion

    @model_validator(mode="after")
    def validate_task_runtime_contract(self) -> TaskRuntimeSettings:
        """
        校验任务运行时配置。
        :returns: 当前模型实例。
        :rtype: TaskRuntimeSettings
        :raises ValueError: 当外层与内层不一致时抛出。
        """

        if self.backend.value != self.backend_detail.kind:
            raise ValueError("runtime.task.backend 必须与 runtime.task.backend_detail.kind 一致。")
        return self


class OtelRuntimeSettings(BaseModel):
    """
    OpenTelemetry运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar enabled: 功能是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enabled: bool
    :ivar service_name: 遥测服务名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype service_name: str
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    service_name: str
    exporter_endpoint: str
    traces_sample_ratio: float = Field(ge=0.0, le=1.0)


class LoggingRuntimeModel(LoggingRuntimeSettings):
    """
    日志运行时Pydantic 模型，用于承载并校验结构化数据。
    """


class MetricsRuntimeModel(MetricsRuntimeEnvelope):
    """
    指标运行时Pydantic 模型，用于承载并校验结构化数据。
    """


class RuntimeSettings(BaseModel):
    """
    运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar web: ``web`` 字段。约束：需符合 ``WebRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype web: WebRuntimeSettings
    :ivar security: 安全运行时配置。约束：需符合 ``SecurityRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载安全公开面策略。
    :vartype security: SecurityRuntimeSettings
    :ivar auth: ``auth`` 字段。约束：需符合 ``AuthRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype auth: AuthRuntimeSettings
    :ivar database: ``database`` 字段。约束：需符合 ``DatabaseRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype database: DatabaseRuntimeSettings
    :ivar cache: ``cache`` 字段。约束：需符合 ``CacheRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype cache: CacheRuntimeSettings
    :ivar message: 消息文本。约束：需符合 ``MessageRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype message: MessageRuntimeSettings
    :ivar task: ``task`` 字段。约束：需符合 ``TaskRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype task: TaskRuntimeSettings
    :ivar otel: ``otel`` 字段。约束：需符合 ``OtelRuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype otel: OtelRuntimeSettings
    :ivar logging: ``logging`` 字段。约束：需符合 ``LoggingRuntimeModel`` 注解。默认值：无，必须显式提供。取值语义：用于承载日志运行时配置与数据库落库策略。
    :vartype logging: LoggingRuntimeModel
    """

    model_config = ConfigDict(extra="forbid")

    web: WebRuntimeSettings
    security: SecurityRuntimeSettings
    distributed_lock: DistributedLockRuntimeEnvelope
    key_management: KeyManagementRuntimeEnvelope
    auth: AuthRuntimeSettings
    database: DatabaseRuntimeSettings
    cache: CacheRuntimeSettings
    message: MessageRuntimeSettings
    task: TaskRuntimeSettings
    otel: OtelRuntimeSettings
    metrics: MetricsRuntimeModel
    logging: LoggingRuntimeModel


class ApplicationSettings(BaseModel):
    """
    应用Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar app: ``app`` 字段。约束：需符合 ``ApplicationMetaSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype app: ApplicationMetaSettings
    :ivar modules: ``modules`` 字段。约束：需符合 ``ModuleSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype modules: ModuleSettings
    :ivar runtime: ``runtime`` 字段。约束：需符合 ``RuntimeSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype runtime: RuntimeSettings
    """

    model_config = ConfigDict(extra="forbid")

    app: ApplicationMetaSettings
    modules: ModuleSettings
    runtime: RuntimeSettings
