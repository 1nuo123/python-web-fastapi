"""共享运行时资源常量。"""

from __future__ import annotations

from src.application.ports.admin_audit_query_port import AdminAuditAction

RESOURCE_HTTP_CLIENT = "shared_http_client"

RESOURCE_ASYNC_HTTP_CLIENT = "shared_async_http_client"

RESOURCE_DATABASE = "shared_database"

RESOURCE_CACHE = "shared_cache"

RESOURCE_TASK_MESSAGE_TRANSPORT = "shared_task_message_transport"

RESOURCE_TASK = "shared_task_dispatcher"

RESOURCE_LOGGING = "shared_logging"

RESOURCE_DISTRIBUTED_LOCK = "shared_distributed_lock"

RESOURCE_KEY_MANAGEMENT = "shared_key_management"

RESOURCE_SECURITY_PROTECTION = "shared_security_protection"

TASK_RESOURCE_READY_DETAIL = "任务基础设施已完成装配。"

LOCAL_MESSAGE_RESOURCE_READY_DETAIL = "local task message transport 已挂载。"

RABBITMQ_MESSAGE_RESOURCE_READY_DETAIL = "rabbitmq task message transport 已挂载。"

FUNBOOST_RABBITMQ_BROKER_RESOURCE_DETAIL = "funboost rabbitmq broker 由任务后端独立管理。"

SETTINGS_APPLY_OPERATION_NAME = "apply_settings"

SETTINGS_APPLY_TARGET_RESOURCE = "shared_resource_mount"

LOGGER_RESOURCE_NOT_READY_MESSAGE = "结构化日志处理器尚未就绪。"

AUTH_THROTTLE_NOT_READY_MESSAGE = "鉴权频控尚未就绪。"

SESSION_FACTORY_NOT_READY_MESSAGE = "数据库会话工厂尚未就绪。"

UNIT_OF_WORK_NOT_READY_MESSAGE = "数据库工作单元尚未就绪。"

TASK_EXECUTION_STORE_NOT_READY_MESSAGE = "任务执行记录存储尚未就绪。"

CACHE_STORE_NOT_READY_MESSAGE = "缓存尚未就绪。"

CACHE_SERVICE_NOT_READY_MESSAGE = "缓存服务尚未就绪。"

DISTRIBUTED_LOCK_NOT_READY_MESSAGE = "分布式锁尚未就绪。"

KEY_MANAGEMENT_NOT_READY_MESSAGE = "密钥管理尚未就绪。"

SECURITY_PROTECTION_NOT_READY_MESSAGE = "安全防护尚未就绪。"

CLIENT_IP_RESOLVER_NOT_READY_MESSAGE = "客户端 IP 解析器尚未就绪。"

MESSAGE_BUS_NOT_READY_MESSAGE = "消息总线尚未就绪。"

LOCAL_MESSAGE_LIST_UNAVAILABLE_MESSAGE = "当前消息总线后端不提供本地消息列表。"

TASK_DISPATCHER_NOT_READY_MESSAGE = "任务调度器尚未就绪。"

TASK_PAYLOAD_JSON_INVALID_MESSAGE = "任务 `{job_kind}` 的 payload_json 校验失败。"

TASK_PAYLOAD_HANDLER_MISSING_MESSAGE = "任务 `{job_kind}` 尚未绑定处理器。"

LOG_DETAIL_UNPARSEABLE_SUMMARY = "历史日志详情无法按当前强类型契约解析。"

ADMIN_AUDIT_SUMMARY_TEMPLATE = "{actor_subject_id} 对 {target_kind}:{target_id} 执行 {action}。"

ADMIN_AUDIT_OPERATION_USER_CREATE = "user_create"

ADMIN_AUDIT_OPERATION_USER_UPDATE = "user_update"

ADMIN_AUDIT_OPERATION_USER_DELETE = "user_delete"

ADMIN_AUDIT_OPERATION_USER_DISABLE = "user_disable"

ADMIN_AUDIT_OPERATION_USER_ENABLE = "user_enable"

ADMIN_AUDIT_OPERATION_PASSWORD_RESET = "user_password_reset"

ADMIN_AUDIT_OPERATION_ROLE_REPLACE = "user_role_replace"

ADMIN_AUDIT_OPERATION_BY_ACTION: dict[AdminAuditAction, tuple[str, ...]] = {
    AdminAuditAction.USER_CREATED: (ADMIN_AUDIT_OPERATION_USER_CREATE,),
    AdminAuditAction.USER_UPDATED: (ADMIN_AUDIT_OPERATION_USER_UPDATE,),
    AdminAuditAction.USER_DISABLED: (
        ADMIN_AUDIT_OPERATION_USER_DELETE,
        ADMIN_AUDIT_OPERATION_USER_DISABLE,
    ),
    AdminAuditAction.USER_ENABLED: (ADMIN_AUDIT_OPERATION_USER_ENABLE,),
    AdminAuditAction.PASSWORD_RESET: (ADMIN_AUDIT_OPERATION_PASSWORD_RESET,),
    AdminAuditAction.ROLE_ASSIGNED: (ADMIN_AUDIT_OPERATION_ROLE_REPLACE,),
}

ADMIN_AUDIT_OPERATION_NAMES: tuple[str, ...] = tuple(
    operation_name
    for operation_names in ADMIN_AUDIT_OPERATION_BY_ACTION.values()
    for operation_name in operation_names
)

ADMIN_AUDIT_ACTION_BY_OPERATION: dict[str, AdminAuditAction] = {
    operation_name: action
    for action, operation_names in ADMIN_AUDIT_OPERATION_BY_ACTION.items()
    for operation_name in operation_names
}

REQUEST_EXECUTION_BRIDGE_NOT_READY_MESSAGE = "请求执行桥接器尚未就绪。"

ASYNC_HTTP_CLIENT_NOT_READY_MESSAGE = "异步 HTTP 客户端尚未就绪。"

SYNC_HTTP_CLIENT_NOT_READY_MESSAGE = "同步 HTTP 客户端尚未就绪。"

DATABASE_LOGGING_CONFIG_INVALID_MESSAGE = "日志落库配置无效。"

DATABASE_RESOURCE_NOT_READY_MESSAGE = "日志依赖的数据库资源尚未就绪。"

MEMORY_CACHE_CONFIG_INVALID_MESSAGE = "内存缓存配置无效。"

REDIS_CACHE_CONFIG_INVALID_MESSAGE = "Redis 缓存配置无效。"

RABBITMQ_CONFIG_INVALID_MESSAGE = "RabbitMQ 地址配置无效。"

RABBITMQ_PROBE_FAILED_MESSAGE = "RabbitMQ 启动探测失败。"

RESOURCE_STARTUP_BEGIN_MESSAGE = "开始初始化共享资源。"

RESOURCE_STARTUP_FINISH_MESSAGE = "共享资源初始化完成。"

RESOURCE_STARTUP_FAILED_MESSAGE = "共享资源初始化失败：%s"

RESOURCE_RELEASE_BEGIN_MESSAGE = "开始释放共享资源。"

RESOURCE_RELEASE_FINISH_MESSAGE = "共享资源已释放。"

PRODUCTION_BOOTSTRAP_ADMIN_BLOCKED_MESSAGE = "生产环境禁止在常驻启动流程中启用 bootstrap admin。"

PRODUCTION_MEMORY_CACHE_BLOCKED_MESSAGE = "生产环境禁止使用内存缓存承载认证节流。"

ATTACH_HTTP_RUNTIME_OPERATION_NAME = "attach_http_runtime"

INSTALL_DATABASE_RUNTIME_OPERATION_NAME = "install_database_runtime"

INSTALL_LOGGING_RUNTIME_OPERATION_NAME = "install_logging_runtime"

INSTALL_CACHE_RUNTIME_OPERATION_NAME = "install_cache_runtime"

INSTALL_TASK_RUNTIME_OPERATION_NAME = "install_task_runtime"

REFRESH_RUNTIME_ACCESSORS_OPERATION_NAME = "refresh_runtime_accessors"

MARK_RUNTIME_RESOURCE_STATE_OPERATION_NAME = "mark_runtime_resource_state"

TASK_OUTBOX_PUBLISHER_NOT_READY_MESSAGE = "任务 Outbox 发布器尚未就绪。"
