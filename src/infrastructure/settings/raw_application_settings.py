"""应用配置原始映射基础设施模块。"""

from __future__ import annotations

from typing import TypedDict


class RawRedisResourceHeaderMapping(TypedDict, total=False):
    """原始共享 Redis 资源公共头。"""

    kind: str
    schema_version: str
    enabled: bool


class RawRedisResourceDetailMapping(TypedDict, total=False):
    """原始共享 Redis 资源强类型扩展字段。"""

    kind: str
    schema_version: str
    url: str
    connect_timeout_seconds: float
    operation_timeout_seconds: float
    sync_max_connections: int
    async_max_connections: int
    health_probe_timeout_seconds: float
    require_tls_in_production: bool


class RawRedisResourceRuntimeMapping(TypedDict, total=False):
    """原始共享 Redis 资源信封。"""

    header: RawRedisResourceHeaderMapping
    detail: RawRedisResourceDetailMapping


class RawApplicationModuleSwitchMapping(TypedDict, total=False):
    """
    原始应用模块开关映射TypedDict 映射，用于描述结构化字典输入。

    :ivar enabled: 功能是否启用。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enabled: list[str]
    """

    enabled: list[str]


class RawApplicationReloadPolicyMapping(TypedDict, total=False):
    """
    原始应用重载策略映射TypedDict 映射，用于描述结构化字典输入。

    :ivar hot_reload_allowed: ``hot_reload_allowed`` 字段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype hot_reload_allowed: list[str]
    :ivar restart_required: ``restart_required`` 字段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype restart_required: list[str]
    """

    hot_reload_allowed: list[str]
    restart_required: list[str]


class RawApplicationMetaMapping(TypedDict, total=False):
    """
    原始应用元信息映射TypedDict 映射，用于描述结构化字典输入。

    :ivar name: ``name`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype name: str
    :ivar version: ``version`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype version: str
    :ivar environment: ``environment`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype environment: str
    :ivar enable_openapi: ``enable_openapi`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enable_openapi: bool
    :ivar modules: ``modules`` 字段。约束：需符合 ``RawApplicationModuleSwitchMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype modules: RawApplicationModuleSwitchMapping
    :ivar reload: ``reload`` 字段。约束：需符合 ``RawApplicationReloadPolicyMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype reload: RawApplicationReloadPolicyMapping
    """

    name: str
    version: str
    environment: str
    enable_openapi: bool
    modules: RawApplicationModuleSwitchMapping
    reload: RawApplicationReloadPolicyMapping


class RawBootstrapAdminMapping(TypedDict, total=False):
    """
    原始引导管理员映射TypedDict 映射，用于描述结构化字典输入。

    :ivar enabled: 功能是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enabled: bool
    :ivar username: 登录用户名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str
    :ivar password_plain: 明文密码。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_plain: str
    :ivar subject_id: 认证主体标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str
    :ivar role_bindings: ``role_bindings`` 字段。约束：需符合 ``list['RawBootstrapRoleBindingMapping']`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于描述角色标识或角色关联关系。
    :vartype role_bindings: list['RawBootstrapRoleBindingMapping']
    """

    enabled: bool
    username: str
    password_plain: str
    subject_id: str
    role_bindings: list[RawBootstrapRoleBindingMapping]


class RawBootstrapRoleBindingMapping(TypedDict, total=False):
    """
    原始引导角色绑定映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar role_key: ``role_key`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于描述角色标识或角色关联关系。
    :vartype role_key: str
    :ivar scope_codes: 作用域编码列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于声明授权作用域或请求作用域。
    :vartype scope_codes: list[str]
    """

    kind: str
    schema_version: str
    role_key: str
    scope_codes: list[str]


class RawPublicRegistrationMapping(TypedDict, total=False):
    """原始公开注册策略映射。"""

    enabled: bool
    default_role_key: str


class RawSystemModuleMapping(TypedDict, total=False):
    """
    原始系统模块映射TypedDict 映射，用于描述结构化字典输入。

    :ivar ready_probe_enabled: ``ready_probe_enabled`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype ready_probe_enabled: bool
    :ivar overview_title: ``overview_title`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype overview_title: str
    """

    ready_probe_enabled: bool
    overview_title: str


class RawAuthModuleMapping(TypedDict, total=False):
    """
    原始鉴权模块映射TypedDict 映射，用于描述结构化字典输入。

    :ivar bootstrap_admin: ``bootstrap_admin`` 字段。约束：需符合 ``RawBootstrapAdminMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype bootstrap_admin: RawBootstrapAdminMapping
    """

    bootstrap_admin: RawBootstrapAdminMapping
    public_registration: RawPublicRegistrationMapping


class RawTaskModuleMapping(TypedDict, total=False):
    """
    原始任务模块映射TypedDict 映射，用于描述结构化字典输入。

    :ivar default_retry_limit: 默认重试次数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype default_retry_limit: int
    :ivar default_job_kind: 默认任务类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype default_job_kind: str
    """

    default_retry_limit: int
    default_job_kind: str
    registrations: list[RawTaskRegistrationEnvelopeMapping]


class RawCodexControlModuleMapping(TypedDict, total=False):
    """原始 Codex 控制面模块配置。"""

    personal_mvp_only: bool


class RawTaskRegistrationHeaderMapping(TypedDict, total=False):
    """
    原始任务注册公共头映射TypedDict。

    :ivar header_kind: 公共头类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判定任务注册公共头的结构类型。
    :vartype header_kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于约束公共头与扩展字段的版本一致性。
    :vartype schema_version: str
    :ivar task_name: 任务定义名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达业务侧可读的任务名称。
    :vartype task_name: str
    :ivar job_kind: 任务类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于在注册中心、分发器和处理器之间建立稳定绑定。
    :vartype job_kind: str
    :ivar enabled: 任务是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示允许注册与分发，``False`` 表示保留配置但不参与运行。
    :vartype enabled: bool
    :ivar backend: 目标任务后端。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于声明该注册项应由本地后端还是 Funboost 后端承接。
    :vartype backend: str
    """

    header_kind: str
    schema_version: str
    task_name: str
    job_kind: str
    enabled: bool
    backend: str


class RawLocalTaskRegistrationDetailMapping(TypedDict, total=False):
    """
    原始本地任务注册扩展映射TypedDict。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别本地任务注册扩展模型。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与外层任务注册版本一致。
    :vartype schema_version: str
    :ivar retry_limit: 任务最大重试次数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于控制本地任务失败后的重试上限。
    :vartype retry_limit: int
    """

    kind: str
    schema_version: str
    retry_limit: int


class RawFunboostTaskRegistrationDetailMapping(TypedDict, total=False):
    """
    原始 Funboost 任务注册扩展映射TypedDict。

    当前快速开发阶段 ``queue_name``、``exchange_name``、``routing_key``、``broker_kind``、
    ``retry_limit``、``consumer_worker_count`` 已映射到 Funboost 装配链路。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别 Funboost 任务注册扩展模型。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与外层任务注册版本一致。
    :vartype schema_version: str
    :ivar queue_name: 目标队列名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于声明消费者监听队列与发布目标队列。
    :vartype queue_name: str
    :ivar exchange_name: 交换机名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与 RabbitMQ 运行时交换机配置保持一致。
    :vartype exchange_name: str
    :ivar routing_key: 路由键。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于消息发布和队列绑定路由。
    :vartype routing_key: str
    :ivar broker_kind: Broker 类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于声明当前任务注册所依赖的消息代理模型。
    :vartype broker_kind: str
    :ivar retry_limit: 任务最大重试次数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于控制 Funboost 消费失败后的最大重试次数。
    :vartype retry_limit: int
    :ivar consumer_worker_count: 消费者工作线程数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于控制单任务类型的本地消费并发度。
    :vartype consumer_worker_count: int
    """

    kind: str
    schema_version: str
    queue_name: str
    exchange_name: str
    routing_key: str
    broker_kind: str
    retry_limit: int
    consumer_worker_count: int


class RawTaskRegistrationEnvelopeMapping(TypedDict, total=False):
    """
    原始任务注册信封映射TypedDict。

    :ivar envelope_kind: 外层信封类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判定当前配置块属于任务注册。
    :vartype envelope_kind: str
    :ivar schema_version: 外层信封版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于约束任务注册公共头与扩展字段的一致性。
    :vartype schema_version: str
    :ivar header: 公共头字段。约束：需符合 ``RawTaskRegistrationHeaderMapping`` 注解。默认值：无，必须显式提供。取值语义：承载全部任务注册共享的基础信息。
    :vartype header: RawTaskRegistrationHeaderMapping
    :ivar detail: 强类型扩展字段。约束：需符合 ``RawLocalTaskRegistrationDetailMapping | RawFunboostTaskRegistrationDetailMapping`` 注解。默认值：无，必须显式提供。取值语义：承载后端专属注册参数。
    :vartype detail: RawLocalTaskRegistrationDetailMapping | RawFunboostTaskRegistrationDetailMapping
    """

    envelope_kind: str
    schema_version: str
    header: RawTaskRegistrationHeaderMapping
    detail: RawLocalTaskRegistrationDetailMapping | RawFunboostTaskRegistrationDetailMapping


class RawLocalMessageBackendDetailMapping(TypedDict, total=False):
    """
    原始本地消息后端扩展映射TypedDict。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别本地消息后端扩展模型。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与消息运行时外层版本一致。
    :vartype schema_version: str
    """

    kind: str
    schema_version: str
    max_items: int


class RawRabbitMqMessageBackendDetailMapping(TypedDict, total=False):
    """
    原始 RabbitMQ 消息后端扩展映射TypedDict。

    ``rabbitmq_url``、启动探测、交换机、消息持久化和发布确认字段均由独立
    RabbitMQ 消息总线与 Funboost 任务主链共同消费，并统一执行持久化、发布确认、
    有界队列、预取和死信配置。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别 RabbitMQ 消息后端扩展模型。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与消息运行时外层版本一致。
    :vartype schema_version: str
    :ivar rabbitmq_url: RabbitMQ 连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于生成探活连接、发布连接与消费连接。
    :vartype rabbitmq_url: str
    :ivar startup_probe_enabled: 是否启用启动探测。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启动期探测 RabbitMQ 可达性。
    :vartype startup_probe_enabled: bool
    :ivar startup_probe_timeout_seconds: 启动探测超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于限制 RabbitMQ 启动探测等待时长。
    :vartype startup_probe_timeout_seconds: int
    :ivar task_exchange_name: 任务交换机名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：当前为预留字段，实际装配使用任务注册项中的 ``exchange_name``。
    :vartype task_exchange_name: str
    :ivar task_exchange_type: 任务交换机类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于控制 RabbitMQ 交换机路由行为。
    :vartype task_exchange_type: str
    :ivar task_exchange_durable: 任务交换机是否持久化。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示交换机声明为持久化。
    :vartype task_exchange_durable: bool
    :ivar task_message_persistent: 任务消息是否持久化。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：控制 RabbitMQ 消息 delivery mode。
    :vartype task_message_persistent: bool
    :ivar publisher_confirm_enabled: 是否启用发布确认。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：控制生产发布链是否等待 broker 确认。
    :vartype publisher_confirm_enabled: bool
    :ivar publisher_confirm_timeout_seconds: 发布确认超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：限制发布确认 RPC 等待时间。
    :vartype publisher_confirm_timeout_seconds: int
    """

    kind: str
    schema_version: str
    rabbitmq_url: str
    startup_probe_enabled: bool
    startup_probe_timeout_seconds: int
    task_exchange_name: str
    task_exchange_type: str
    task_exchange_durable: bool
    task_message_persistent: bool
    publisher_confirm_enabled: bool
    publisher_confirm_timeout_seconds: int
    queue_max_length: int
    consumer_prefetch_count: int
    dead_letter_exchange_name: str


class RawLocalTaskBackendDetailMapping(TypedDict, total=False):
    """
    原始本地任务后端扩展映射TypedDict。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别本地任务后端扩展模型。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与任务运行时外层版本一致。
    :vartype schema_version: str
    :ivar inline_execute_enabled: 本地任务是否同进程执行处理器。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示本地派发后立即执行处理器。
    :vartype inline_execute_enabled: bool
    """

    kind: str
    schema_version: str
    inline_execute_enabled: bool


class RawFunboostTaskBackendDetailMapping(TypedDict, total=False):
    """
    原始 Funboost 任务后端扩展映射TypedDict。

    ``broker_kind`` 参与运行时与注册项一致性校验；重试退避参数直接驱动
    Funboost 任务运行时，任务级并发和重试次数由注册项字段控制。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别 Funboost 任务后端扩展模型。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与任务运行时外层版本一致。
    :vartype schema_version: str
    :ivar broker_kind: Broker 类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：要求与具体任务注册项的 broker_kind 一致。
    :vartype broker_kind: str
    :ivar retry_limit: 默认重试次数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：当前为预留字段，实际重试上限使用任务注册项配置。
    :vartype retry_limit: int
    """

    kind: str
    schema_version: str
    broker_kind: str


class RawRuntimeCorsMapping(TypedDict, total=False):
    """
    原始 CORS 运行时映射。

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

    enabled: bool
    allow_origins: list[str]
    allow_methods: list[str]
    allow_headers: list[str]
    allow_credentials: bool


class RawWebRuntimeMapping(TypedDict, total=False):
    """
    原始Web运行时映射TypedDict 映射，用于描述结构化字典输入。

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
    :ivar request_execution: 请求执行策略配置。约束：需符合 ``RawRequestExecutionMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype request_execution: RawRequestExecutionMapping
    :ivar outbound_http_client: 外部 HTTP 客户端配置。约束：需符合 ``RawOutboundHttpClientMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype outbound_http_client: RawOutboundHttpClientMapping
    :ivar cors: CORS 运行时配置。
    :vartype cors: RawRuntimeCorsMapping
    """

    api_prefix: str
    max_request_body_bytes: int
    enable_access_log: bool
    enable_security_headers: bool
    include_middleware_trace_header: bool
    cors: RawRuntimeCorsMapping
    request_execution: RawRequestExecutionMapping
    outbound_http_client: RawOutboundHttpClientMapping


class RawRequestExecutionHeaderMapping(TypedDict, total=False):
    """
    原始请求执行公共头映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 公共头类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判定请求执行公共头结构。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于约束公共头与扩展字段版本一致。
    :vartype schema_version: str
    :ivar execution_name: 执行策略名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于把路由调用点与运行时执行策略显式绑定。
    :vartype execution_name: str
    :ivar enabled: 是否启用执行策略。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示按配置策略执行，``False`` 表示退回默认线程池兜底。
    :vartype enabled: bool
    :ivar mode: 执行模式。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于声明线程池模式或原生异步模式。
    :vartype mode: str
    """

    kind: str
    schema_version: str
    execution_name: str
    enabled: bool
    mode: str


class RawThreadpoolExecutionDetailMapping(TypedDict, total=False):
    """
    原始线程池执行扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别线程池执行扩展。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与请求执行外层版本一致。
    :vartype schema_version: str
    :ivar offload_timeout_seconds: 线程池卸载超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于限制同步用例在桥接器中的最大执行时长。
    :vartype offload_timeout_seconds: int
    """

    kind: str
    schema_version: str
    offload_timeout_seconds: int
    max_workers: int
    max_pending_requests: int
    queue_wait_timeout_seconds: int


class RawNativeAsyncExecutionDetailMapping(TypedDict, total=False):
    """
    原始原生异步执行扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别原生异步执行扩展。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与请求执行外层版本一致。
    :vartype schema_version: str
    :ivar propagate_cancellation: 是否传播协程取消信号。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示协程可感知取消，``False`` 表示使用屏蔽等待。
    :vartype propagate_cancellation: bool
    """

    kind: str
    schema_version: str
    propagate_cancellation: bool


class RawRequestExecutionMapping(TypedDict, total=False):
    """
    原始请求执行配置映射TypedDict 映射，用于描述结构化字典输入。

    :ivar envelope_kind: 外层信封类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判定当前配置块属于请求执行策略。
    :vartype envelope_kind: str
    :ivar schema_version: 外层信封版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于约束公共头与扩展字段版本一致。
    :vartype schema_version: str
    :ivar header: 公共头字段。约束：需符合 ``RawRequestExecutionHeaderMapping`` 注解。默认值：无，必须显式提供。取值语义：承载执行名称、启用状态和执行模式。
    :vartype header: RawRequestExecutionHeaderMapping
    :ivar detail: 强类型扩展字段。约束：需符合 ``RawThreadpoolExecutionDetailMapping | RawNativeAsyncExecutionDetailMapping`` 注解。默认值：无，必须显式提供。取值语义：承载具体模式下的执行细节。
    :vartype detail: RawThreadpoolExecutionDetailMapping | RawNativeAsyncExecutionDetailMapping
    """

    envelope_kind: str
    schema_version: str
    header: RawRequestExecutionHeaderMapping
    detail: RawThreadpoolExecutionDetailMapping | RawNativeAsyncExecutionDetailMapping


class RawOutboundHttpClientHeaderMapping(TypedDict, total=False):
    """
    原始外部 HTTP 客户端公共头映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 公共头类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判定外部 HTTP 客户端公共头结构。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于约束公共头与扩展字段版本一致。
    :vartype schema_version: str
    :ivar client_name: 客户端配置名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于标识当前装配的外部 HTTP 客户端。
    :vartype client_name: str
    :ivar enabled: 是否启用客户端能力。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示允许装配客户端能力。
    :vartype enabled: bool
    :ivar mode: 客户端模式。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于声明同步模式或异步模式。
    :vartype mode: str
    """

    kind: str
    schema_version: str
    client_name: str
    enabled: bool
    mode: str


class RawSyncHttpClientDetailMapping(TypedDict, total=False):
    """
    原始同步 HTTP 客户端扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别同步 HTTP 客户端扩展。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与外部 HTTP 客户端外层版本一致。
    :vartype schema_version: str
    :ivar timeout_seconds: 请求超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于控制同步客户端的统一超时。
    :vartype timeout_seconds: int
    """

    kind: str
    schema_version: str
    timeout_seconds: int
    max_connections: int
    max_keepalive_connections: int


class RawAsyncHttpClientDetailMapping(TypedDict, total=False):
    """
    原始异步 HTTP 客户端扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判别异步 HTTP 客户端扩展。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：必须与外部 HTTP 客户端外层版本一致。
    :vartype schema_version: str
    :ivar timeout_seconds: 请求超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于控制异步客户端的统一超时。
    :vartype timeout_seconds: int
    :ivar max_connections: 最大连接数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于限制异步客户端的总体连接上限。
    :vartype max_connections: int
    :ivar max_keepalive_connections: 最大保活连接数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于控制可复用的长连接数量。
    :vartype max_keepalive_connections: int
    """

    kind: str
    schema_version: str
    timeout_seconds: int
    max_connections: int
    max_keepalive_connections: int


class RawOutboundHttpClientMapping(TypedDict, total=False):
    """
    原始外部 HTTP 客户端配置映射TypedDict 映射，用于描述结构化字典输入。

    :ivar envelope_kind: 外层信封类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于判定当前配置块属于外部 HTTP 客户端能力。
    :vartype envelope_kind: str
    :ivar schema_version: 外层信封版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于约束公共头与扩展字段版本一致。
    :vartype schema_version: str
    :ivar header: 公共头字段。约束：需符合 ``RawOutboundHttpClientHeaderMapping`` 注解。默认值：无，必须显式提供。取值语义：承载客户端名称、启用状态与模式。
    :vartype header: RawOutboundHttpClientHeaderMapping
    :ivar detail: 强类型扩展字段。约束：需符合 ``RawSyncHttpClientDetailMapping | RawAsyncHttpClientDetailMapping`` 注解。默认值：无，必须显式提供。取值语义：承载同步或异步客户端专属参数。
    :vartype detail: RawSyncHttpClientDetailMapping | RawAsyncHttpClientDetailMapping
    """

    envelope_kind: str
    schema_version: str
    header: RawOutboundHttpClientHeaderMapping
    detail: RawSyncHttpClientDetailMapping | RawAsyncHttpClientDetailMapping


class RawSecurityRuntimeHeaderMapping(TypedDict, total=False):
    """
    原始安全运行时公共头映射。

    :ivar kind: 公共头类型标识。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: str
    :ivar mode: 安全运行时模式。
    :vartype mode: str
    :ivar enabled: 安全策略是否启用。
    :vartype enabled: bool
    :ivar policy_name: 安全策略名称。
    :vartype policy_name: str
    """

    kind: str
    schema_version: str
    mode: str
    enabled: bool
    policy_name: str


class RawDevelopmentSecurityRuntimeDetailMapping(TypedDict, total=False):
    """
    原始开发安全运行时扩展映射。

    :ivar kind: 扩展字段类型标识。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: str
    :ivar expose_openapi: 是否允许暴露 OpenAPI。
    :vartype expose_openapi: bool
    :ivar expose_system_info: 是否允许匿名暴露系统信息。
    :vartype expose_system_info: bool
    :ivar require_external_jwt_secret: 是否要求 JWT 密钥来自外部注入。
    :vartype require_external_jwt_secret: bool
    :ivar require_distributed_auth_throttle: 是否要求分布式鉴权节流。
    :vartype require_distributed_auth_throttle: bool
    :ivar enable_hsts: 是否启用 HSTS。
    :vartype enable_hsts: bool
    :ivar enable_csp: 是否启用 CSP。
    :vartype enable_csp: bool
    """

    kind: str
    schema_version: str
    expose_openapi: bool
    expose_system_info: bool
    require_external_jwt_secret: bool
    require_distributed_auth_throttle: bool
    enable_hsts: bool
    enable_csp: bool


class RawProductionSecurityRuntimeDetailMapping(
    RawDevelopmentSecurityRuntimeDetailMapping,
    total=False,
):
    """
    原始生产安全运行时扩展映射。
    """


class RawSecurityRuntimeMapping(TypedDict, total=False):
    """
    原始安全运行时信封映射。

    :ivar envelope_kind: 外层信封类型标识。
    :vartype envelope_kind: str
    :ivar schema_version: 外层信封版本。
    :vartype schema_version: str
    :ivar header: 公共头字段。
    :vartype header: RawSecurityRuntimeHeaderMapping
    :ivar detail: 强类型扩展字段。
    :vartype detail: RawDevelopmentSecurityRuntimeDetailMapping | RawProductionSecurityRuntimeDetailMapping
    """

    envelope_kind: str
    schema_version: str
    header: RawSecurityRuntimeHeaderMapping
    detail: RawDevelopmentSecurityRuntimeDetailMapping | RawProductionSecurityRuntimeDetailMapping


class RawAuthRuntimeMapping(TypedDict, total=False):
    """
    原始鉴权运行时映射TypedDict 映射，用于描述结构化字典输入。

    :ivar jwt_secret: JWT 签名密钥。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype jwt_secret: str
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
    :ivar password_hash_algorithm: ``password_hash_algorithm`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_hash_algorithm: str
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

    jwt_secret: str
    jwt_algorithm: str
    access_token_expires_in_seconds: int
    refresh_token_expires_in_seconds: int
    issuer: str
    audience: str
    password_hash_algorithm: str
    refresh_token_rotation_enabled: bool
    issue_access_token_failure_limit: int
    issue_access_token_failure_window_seconds: int
    refresh_access_token_failure_limit: int
    refresh_access_token_failure_window_seconds: int
    throttle_lock_seconds: int


class RawDatabaseRuntimeMapping(TypedDict, total=False):
    """
    原始数据库运行时映射TypedDict 映射，用于描述结构化字典输入。

    :ivar backend: 后端类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: str
    :ivar url: 数据库连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于连接外部资源或数据库。
    :vartype url: str
    :ivar schema: ``schema`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype schema: str
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

    backend: str
    url: str
    schema: str
    echo: bool
    pool_size: int
    max_overflow: int
    pool_recycle_seconds: int
    connect_timeout_seconds: int
    auto_upgrade_on_startup: bool
    statement_timeout_seconds: int


class RawMemoryCacheBackendDetailMapping(TypedDict, total=False):
    """
    原始内存缓存后端详情映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar max_entries: 内存缓存最大条目数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype max_entries: int
    """

    kind: str
    schema_version: str
    max_entries: int


class RawRedisCacheBackendDetailMapping(TypedDict, total=False):
    """
    原始Redis缓存后端详情映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar redis_url: Redis 连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于连接外部资源或数据库。
    :vartype redis_url: str
    :ivar socket_connect_timeout_seconds: Redis 连接超时秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype socket_connect_timeout_seconds: int
    """

    kind: str
    schema_version: str
    redis_url: str
    socket_connect_timeout_seconds: int
    max_connections: int


class RawCachePolicyHeaderMapping(TypedDict, total=False):
    """
    原始缓存策略公共头映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 公共头类型标识。约束：需符合 ``str`` 注解。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。
    :vartype schema_version: str
    :ivar detail_kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。
    :vartype detail_kind: str
    :ivar namespace: 缓存命名空间。约束：需符合 ``str`` 注解。
    :vartype namespace: str
    """

    kind: str
    schema_version: str
    detail_kind: str
    namespace: str


class RawAuthThrottleCachePolicyDetailMapping(TypedDict, total=False):
    """
    原始鉴权节流缓存策略扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。
    :vartype schema_version: str
    :ivar namespace: 缓存命名空间。约束：需符合 ``str`` 注解。
    :vartype namespace: str
    :ivar default_ttl_seconds: 默认缓存 TTL 秒数。约束：需符合 ``int`` 注解。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的失败处理模式。约束：需符合 ``str`` 注解。
    :vartype failure_mode: str
    """

    kind: str
    schema_version: str
    namespace: str
    default_ttl_seconds: int
    failure_mode: str


class RawRateLimitCachePolicyDetailMapping(TypedDict, total=False):
    """
    原始限流缓存策略扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。
    :vartype schema_version: str
    :ivar namespace: 缓存命名空间。约束：需符合 ``str`` 注解。
    :vartype namespace: str
    :ivar default_ttl_seconds: 默认缓存 TTL 秒数。约束：需符合 ``int`` 注解。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的失败处理模式。约束：需符合 ``str`` 注解。
    :vartype failure_mode: str
    """

    kind: str
    schema_version: str
    namespace: str
    default_ttl_seconds: int
    failure_mode: str


class RawQueryResultCachePolicyDetailMapping(TypedDict, total=False):
    """
    原始查询缓存策略扩展映射TypedDict 映射，用于描述结构化字典输入。

    :ivar kind: 扩展字段类型标识。约束：需符合 ``str`` 注解。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。
    :vartype schema_version: str
    :ivar namespace: 缓存命名空间。约束：需符合 ``str`` 注解。
    :vartype namespace: str
    :ivar default_ttl_seconds: 默认缓存 TTL 秒数。约束：需符合 ``int`` 注解。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的失败处理模式。约束：需符合 ``str`` 注解。
    :vartype failure_mode: str
    """

    kind: str
    schema_version: str
    namespace: str
    default_ttl_seconds: int
    failure_mode: str


class RawCachePolicyEnvelopeMapping(TypedDict, total=False):
    """
    原始缓存策略信封映射TypedDict 映射，用于描述结构化字典输入。

    :ivar header: 缓存策略公共头。约束：需符合 ``RawCachePolicyHeaderMapping`` 注解。
    :vartype header: RawCachePolicyHeaderMapping
    :ivar detail: 缓存策略强类型扩展字段。约束：需符合缓存策略扩展映射联合。
    :vartype detail: RawAuthThrottleCachePolicyDetailMapping | RawRateLimitCachePolicyDetailMapping | RawQueryResultCachePolicyDetailMapping
    """

    header: RawCachePolicyHeaderMapping
    detail: (
        RawAuthThrottleCachePolicyDetailMapping
        | RawRateLimitCachePolicyDetailMapping
        | RawQueryResultCachePolicyDetailMapping
    )


class RawCacheRuntimeMapping(TypedDict, total=False):
    """
    原始缓存运行时映射TypedDict 映射，用于描述结构化字典输入。

    :ivar backend: 后端类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: str
    :ivar default_ttl_seconds: 默认缓存 TTL 秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype default_ttl_seconds: int
    :ivar key_prefix: 缓存键前缀。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype key_prefix: str
    :ivar backend_detail: 后端明细配置。约束：需符合 ``RawMemoryCacheBackendDetailMapping | RawRedisCacheBackendDetailMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend_detail: RawMemoryCacheBackendDetailMapping | RawRedisCacheBackendDetailMapping
    :ivar namespace_policies: 缓存命名空间策略列表。约束：需符合 ``list[RawCachePolicyEnvelopeMapping]`` 注解。
    :vartype namespace_policies: list[RawCachePolicyEnvelopeMapping]
    """

    backend: str
    default_ttl_seconds: int
    key_prefix: str
    backend_detail: RawMemoryCacheBackendDetailMapping | RawRedisCacheBackendDetailMapping
    namespace_policies: list[RawCachePolicyEnvelopeMapping]


class RawMessageRuntimeMapping(TypedDict, total=False):
    """
    原始消息运行时映射TypedDict 映射，用于描述结构化字典输入。

    :ivar backend: 后端类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: str
    :ivar rabbitmq_url: RabbitMQ 连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于连接外部资源或数据库。
    :vartype rabbitmq_url: str
    """

    backend: str
    backend_detail: RawLocalMessageBackendDetailMapping | RawRabbitMqMessageBackendDetailMapping


class RawTaskRuntimeMapping(TypedDict, total=False):
    """
    原始任务运行时映射TypedDict 映射，用于描述结构化字典输入。

    :ivar backend: 后端类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: str
    :ivar worker_enabled: 任务工作器是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype worker_enabled: bool
    :ivar funboost_queue_name: Funboost 队列名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype funboost_queue_name: str
    """

    backend: str
    worker_enabled: bool
    backend_detail: RawLocalTaskBackendDetailMapping | RawFunboostTaskBackendDetailMapping


class RawOtelRuntimeMapping(TypedDict, total=False):
    """
    原始OpenTelemetry运行时映射TypedDict 映射，用于描述结构化字典输入。

    :ivar enabled: 功能是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enabled: bool
    :ivar service_name: 遥测服务名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype service_name: str
    """

    enabled: bool
    service_name: str
    exporter_endpoint: str
    traces_sample_ratio: float


class RawMetricsRuntimeHeaderMapping(TypedDict, total=False):
    """
    原始指标运行时公共头映射。
    """

    kind: str
    schema_version: str
    mode: str
    enabled: bool
    policy_name: str


class RawPrometheusMetricsRuntimeDetailMapping(TypedDict, total=False):
    """
    原始 Prometheus 指标运行时扩展映射。
    """

    kind: str
    schema_version: str
    metrics_path: str
    include_http_metrics: bool
    include_runtime_metrics: bool
    include_security_metrics: bool
    include_task_metrics: bool
    include_log_buffer_metrics: bool
    include_saturation_metrics: bool
    include_codex_diagnostic_metrics: bool


class RawMetricsRuntimeMapping(TypedDict, total=False):
    """
    原始指标运行时信封映射。
    """

    envelope_kind: str
    schema_version: str
    header: RawMetricsRuntimeHeaderMapping
    detail: RawPrometheusMetricsRuntimeDetailMapping


class RawDatabaseLogSinkDetailMapping(TypedDict, total=False):
    """
    原始数据库日志扩展配置映射TypedDict 映射，用于描述结构化字典输入。
    """

    kind: str
    schema_version: str
    table_name: str
    flush_interval_seconds: int
    max_batch_size: int
    fallback_to_stdout: bool
    retention_days: int


class RawLoggingRuntimeMapping(TypedDict, total=False):
    """
    原始日志运行时映射TypedDict 映射，用于描述结构化字典输入。
    """

    enabled: bool
    level: str
    sink: str
    buffer_max_items: int
    entry_project_name: str
    entry_log_path: str
    sink_detail: RawDatabaseLogSinkDetailMapping


class RawStreamRuntimeHeaderMapping(TypedDict, total=False):
    """原始流运行时公共头映射。"""

    kind: str
    schema_version: str
    mode: str
    enabled: bool


class RawLocalStreamRuntimeDetailMapping(TypedDict, total=False):
    """原始本地流运行时扩展映射。"""

    kind: str
    schema_version: str
    queue_capacity: int
    send_timeout_seconds: float
    max_duration_seconds: float
    max_event_bytes: int
    collection_max_events: int
    collection_max_bytes: int
    collection_timeout_seconds: float
    max_sessions: int
    max_sessions_per_subject: int
    max_sessions_per_ip: int
    max_sessions_per_operation: int
    ticket_ttl_seconds: int
    replay_ttl_seconds: int
    replay_max_events: int
    sse_heartbeat_seconds: int
    sse_retry_milliseconds: int
    websocket_max_message_bytes: int
    websocket_ping_interval_seconds: float
    websocket_ping_timeout_seconds: float
    shutdown_grace_seconds: float
    allowed_origins: list[str]
    require_browser_ticket: bool


class RawRedisStreamRuntimeDetailMapping(RawLocalStreamRuntimeDetailMapping, total=False):
    """原始 Redis 流运行时扩展映射。"""

    redis_url: str
    redis_key_prefix: str
    redis_socket_connect_timeout_seconds: float
    redis_max_connections: int


class RawStreamRuntimeMapping(TypedDict, total=False):
    """原始流运行时信封映射。"""

    envelope_kind: str
    schema_version: str
    header: RawStreamRuntimeHeaderMapping
    detail: RawLocalStreamRuntimeDetailMapping | RawRedisStreamRuntimeDetailMapping


class RawDistributedLockRuntimeHeaderMapping(TypedDict, total=False):
    """原始分布式锁运行时公共头映射。"""

    kind: str
    schema_version: str
    enabled: bool
    policy_name: str


class RawDistributedLockRuntimeDetailMapping(TypedDict, total=False):
    """原始分布式锁运行时扩展映射。"""

    kind: str
    schema_version: str
    backend: str
    lease_seconds: int
    wait_seconds: int


class RawDistributedLockRuntimeMapping(TypedDict, total=False):
    """原始分布式锁运行时信封映射。"""

    envelope_kind: str
    schema_version: str
    header: RawDistributedLockRuntimeHeaderMapping
    detail: RawDistributedLockRuntimeDetailMapping


class RawKeyRotationPolicyMapping(TypedDict, total=False):
    """原始密钥轮换策略映射。"""

    kind: str
    schema_version: str
    enabled: bool
    rotation_interval_seconds: int
    active_key_count: int
    compatibility_window_seconds: int


class RawManagedKeyFamilyMapping(TypedDict, total=False):
    """原始托管密钥族映射。"""

    kind: str
    schema_version: str
    family_name: str
    usage: str
    enabled: bool
    status: str
    current_key_id: str | None
    rotation_policy: RawKeyRotationPolicyMapping


class RawKeyManagementRuntimeHeaderMapping(TypedDict, total=False):
    """原始密钥管理运行时公共头映射。"""

    kind: str
    schema_version: str
    enabled: bool
    policy_name: str


class RawKeyManagementRuntimeDetailMapping(TypedDict, total=False):
    """原始密钥管理运行时扩展映射。"""

    kind: str
    schema_version: str
    backend: str
    key_families: list[RawManagedKeyFamilyMapping]


class RawKeyManagementRuntimeMapping(TypedDict, total=False):
    """原始密钥管理运行时信封映射。"""

    envelope_kind: str
    schema_version: str
    header: RawKeyManagementRuntimeHeaderMapping
    detail: RawKeyManagementRuntimeDetailMapping


class RawCodexContentBudgetsMapping(TypedDict, total=False):
    max_receive_message_bytes: int
    history_page_max_bytes: int
    content_chunk_max_message_bytes: int
    query_inflight_max_bytes: int
    content_read: bool


class RawCodexControlRuntimeMapping(TypedDict, total=False):
    """原始 Codex 控制面运行时配置。"""

    enabled: bool
    agent_deployment_profile: str
    agent_lease_continuity_enabled: bool
    bounded_content_enabled: bool
    content_budgets: RawCodexContentBudgetsMapping
    agent_heartbeat_seconds: int
    agent_offline_after_seconds: int
    agent_hello_timeout_seconds: int
    agent_rpc_ack_timeout_seconds: int
    agent_send_enqueue_timeout_seconds: float
    agent_send_timeout_seconds: float
    agent_close_timeout_seconds: float
    agent_outgoing_queue_max_bytes: int
    agent_query_timeout_seconds: int
    agent_execution_lease_seconds: int
    agent_reconnect_min_seconds: int
    agent_reconnect_max_seconds: int
    max_connected_agents: int
    max_hosts_per_user: int
    max_workspaces_per_host: int
    max_active_turns_per_host: int
    max_active_write_turns_per_workspace: int
    agent_outgoing_queue_size: int
    browser_event_queue_size: int
    agent_event_replay_buffer_size: int
    max_agent_frame_bytes: int
    max_browser_frame_bytes: int
    realtime_ticket_ttl_seconds: int
    pairing_code_ttl_seconds: int
    step_up_grant_ttl_seconds: int
    operation_idempotency_ttl_seconds: int
    turn_runtime_lease_ttl_seconds: int
    turn_runtime_watchdog_seconds: int
    turn_runtime_stalled_after_seconds: int
    enrollment_intent_ttl_seconds: int
    client_diagnostic_error_collection_enabled: bool
    client_diagnostic_performance_collection_enabled: bool
    client_diagnostic_performance_sample_rate: float
    client_diagnostic_cleanup_interval_seconds: int
    client_diagnostic_error_retention_days: int
    client_diagnostic_performance_retention_days: int
    codex_scroll_controller_v2: bool
    codex_realtime_batch_v2: bool
    codex_authority_recovery_v2: bool
    allow_experimental_app_server_api: bool
    minimum_codex_version: str
    blocked_codex_versions: list[str]
    agent_release_version: str
    agent_release_distribution_mode: str
    agent_release_artifact_sha256: str
    agent_release_download_url: str
    agent_release_manifest_url: str
    agent_release_minimum_security_version: str
    agent_release_available: bool


class RawRuntimeRootMapping(TypedDict, total=False):
    """
    原始运行时根映射TypedDict 映射，用于描述结构化字典输入。

    :ivar web: ``web`` 字段。约束：需符合 ``RawWebRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype web: RawWebRuntimeMapping
    :ivar auth: ``auth`` 字段。约束：需符合 ``RawAuthRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype auth: RawAuthRuntimeMapping
    :ivar database: ``database`` 字段。约束：需符合 ``RawDatabaseRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype database: RawDatabaseRuntimeMapping
    :ivar cache: ``cache`` 字段。约束：需符合 ``RawCacheRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype cache: RawCacheRuntimeMapping
    :ivar message: 消息文本。约束：需符合 ``RawMessageRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype message: RawMessageRuntimeMapping
    :ivar task: ``task`` 字段。约束：需符合 ``RawTaskRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype task: RawTaskRuntimeMapping
    :ivar otel: ``otel`` 字段。约束：需符合 ``RawOtelRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype otel: RawOtelRuntimeMapping
    """

    web: RawWebRuntimeMapping
    security: RawSecurityRuntimeMapping
    auth: RawAuthRuntimeMapping
    database: RawDatabaseRuntimeMapping
    cache: RawCacheRuntimeMapping
    redis_resource: RawRedisResourceRuntimeMapping
    message: RawMessageRuntimeMapping
    task: RawTaskRuntimeMapping
    otel: RawOtelRuntimeMapping
    metrics: RawMetricsRuntimeMapping
    logging: RawLoggingRuntimeMapping
    distributed_lock: RawDistributedLockRuntimeMapping
    key_management: RawKeyManagementRuntimeMapping
    stream: RawStreamRuntimeMapping
    codex_control: RawCodexControlRuntimeMapping


class RawSettingsMapping(TypedDict, total=False):
    """
    原始配置映射TypedDict 映射，用于描述结构化字典输入。

    :ivar app: ``app`` 字段。约束：需符合 ``RawApplicationMetaMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype app: RawApplicationMetaMapping
    :ivar system_module: ``system_module`` 字段。约束：需符合 ``RawSystemModuleMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype system_module: RawSystemModuleMapping
    :ivar auth_module: ``auth_module`` 字段。约束：需符合 ``RawAuthModuleMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype auth_module: RawAuthModuleMapping
    :ivar task_module: ``task_module`` 字段。约束：需符合 ``RawTaskModuleMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype task_module: RawTaskModuleMapping
    :ivar runtime: ``runtime`` 字段。约束：需符合 ``RawRuntimeRootMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype runtime: RawRuntimeRootMapping
    """

    app: RawApplicationMetaMapping
    system_module: RawSystemModuleMapping
    auth_module: RawAuthModuleMapping
    task_module: RawTaskModuleMapping
    codex_control_module: RawCodexControlModuleMapping
    runtime: RawRuntimeRootMapping


class SettingsOverrideMapping(RawSettingsMapping, total=False):
    """
    配置覆盖映射类型，用于封装当前模块中的相关行为或状态。
    """

    pass


class RawAppTomlContent(TypedDict, total=False):
    """
    原始应用TOML内容TypedDict 映射，用于描述结构化字典输入。

    :ivar app: ``app`` 字段。约束：需符合 ``RawApplicationMetaMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype app: RawApplicationMetaMapping
    """

    app: RawApplicationMetaMapping


class RawModuleTomlContent(TypedDict, total=False):
    """
    原始模块TOML内容TypedDict 映射，用于描述结构化字典输入。

    :ivar module: ``module`` 字段。约束：需符合 ``RawSystemModuleMapping | RawAuthModuleMapping | RawTaskModuleMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype module: RawSystemModuleMapping | RawAuthModuleMapping | RawTaskModuleMapping
    """

    module: (
        RawSystemModuleMapping
        | RawAuthModuleMapping
        | RawTaskModuleMapping
        | RawCodexControlModuleMapping
    )


class RawRuntimeTomlContent(TypedDict, total=False):
    """
    原始运行时TOML内容TypedDict 映射，用于描述结构化字典输入。

    :ivar runtime: ``runtime`` 字段。约束：需符合 ``RawWebRuntimeMapping | RawAuthRuntimeMapping | RawDatabaseRuntimeMapping | RawCacheRuntimeMapping | RawMessageRuntimeMapping | RawTaskRuntimeMapping | RawOtelRuntimeMapping`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype runtime: RawWebRuntimeMapping | RawAuthRuntimeMapping | RawDatabaseRuntimeMapping | RawCacheRuntimeMapping | RawMessageRuntimeMapping | RawTaskRuntimeMapping | RawOtelRuntimeMapping
    """

    runtime: (
        RawWebRuntimeMapping
        | RawAuthRuntimeMapping
        | RawDatabaseRuntimeMapping
        | RawCacheRuntimeMapping
        | RawMessageRuntimeMapping
        | RawTaskRuntimeMapping
        | RawOtelRuntimeMapping
        | RawCodexControlRuntimeMapping
        | RawMetricsRuntimeMapping
        | RawLoggingRuntimeMapping
        | RawStreamRuntimeMapping
    )


RawTomlContent = RawAppTomlContent | RawModuleTomlContent | RawRuntimeTomlContent
