"""
运行时资源挂载操作契约模块。
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus

RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION: Final = "1.0"
RESOURCE_MOUNT_TARGET_RESOURCE: Final = "shared_resource_mount"
HTTP_RUNTIME_ATTACHED_KIND: Final = "http_runtime_attached"
DATABASE_RUNTIME_ATTACHED_KIND: Final = "database_runtime_attached"
LOGGING_RUNTIME_ATTACHED_KIND: Final = "logging_runtime_attached"
CACHE_RUNTIME_ATTACHED_KIND: Final = "cache_runtime_attached"
TASK_RUNTIME_ATTACHED_KIND: Final = "task_runtime_attached"
RUNTIME_ACCESSORS_REFRESHED_KIND: Final = "runtime_accessors_refreshed"
RUNTIME_RESOURCE_STATE_CHANGED_KIND: Final = "runtime_resource_state_changed"

RuntimeResourceMountOperationKind: TypeAlias = Literal[
    "http_runtime_attached",
    "database_runtime_attached",
    "logging_runtime_attached",
    "cache_runtime_attached",
    "task_runtime_attached",
    "runtime_accessors_refreshed",
    "runtime_resource_state_changed",
]


class RuntimeResourceMountOperationHeader(BaseModel):
    """
    运行时资源挂载操作公共头。

    :ivar kind: 操作扩展类型，必须与 ``detail.kind`` 一致。
    :vartype kind: RuntimeResourceMountOperationKind
    :ivar schema_version: 契约版本，必须与 ``detail.schema_version`` 一致。
    :vartype schema_version: Literal["1.0"]
    :ivar operation_name: 操作名称。
    :vartype operation_name: str
    :ivar target_resource: 操作目标资源。
    :vartype target_resource: str
    :ivar resource_name: 被修改状态的运行时资源名称。
    :vartype resource_name: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: RuntimeResourceMountOperationKind
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    operation_name: str
    target_resource: str = RESOURCE_MOUNT_TARGET_RESOURCE
    resource_name: str


class HttpRuntimeAttachedDetail(BaseModel):
    """
    HTTP 运行时挂载扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["http_runtime_attached"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar sync_status: 同步 HTTP 资源状态。
    :vartype sync_status: RuntimeResourceStatus
    :ivar async_status: 异步 HTTP 资源状态。
    :vartype async_status: RuntimeResourceStatus
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["http_runtime_attached"] = HTTP_RUNTIME_ATTACHED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    sync_status: RuntimeResourceStatus
    async_status: RuntimeResourceStatus


class DatabaseRuntimeAttachedDetail(BaseModel):
    """
    数据库运行时挂载扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["database_runtime_attached"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar session_factory_attached: 是否已挂载会话工厂。
    :vartype session_factory_attached: bool
    :ivar session_manager_attached: 是否已挂载会话管理器。
    :vartype session_manager_attached: bool
    :ivar task_execution_store_attached: 是否已挂载任务执行记录存储。
    :vartype task_execution_store_attached: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["database_runtime_attached"] = DATABASE_RUNTIME_ATTACHED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    session_factory_attached: bool
    session_manager_attached: bool
    task_execution_store_attached: bool


class LoggingRuntimeAttachedDetail(BaseModel):
    """
    日志运行时挂载扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["logging_runtime_attached"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar database_writer_attached: 是否已挂载数据库日志写入器。
    :vartype database_writer_attached: bool
    :ivar buffer_dispatcher_attached: 是否已挂载日志缓冲调度器。
    :vartype buffer_dispatcher_attached: bool
    :ivar structured_handler_attached: 是否已挂载结构化日志处理器。
    :vartype structured_handler_attached: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["logging_runtime_attached"] = LOGGING_RUNTIME_ATTACHED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    database_writer_attached: bool
    buffer_dispatcher_attached: bool
    structured_handler_attached: bool


class CacheRuntimeAttachedDetail(BaseModel):
    """
    缓存运行时挂载扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["cache_runtime_attached"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar cache_store_attached: 是否已挂载缓存存储。
    :vartype cache_store_attached: bool
    :ivar cache_service_attached: 是否已挂载缓存服务。
    :vartype cache_service_attached: bool
    :ivar auth_failure_throttle_attached: 是否已挂载鉴权失败节流器。
    :vartype auth_failure_throttle_attached: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cache_runtime_attached"] = CACHE_RUNTIME_ATTACHED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    cache_store_attached: bool
    cache_service_attached: bool
    auth_failure_throttle_attached: bool


class TaskRuntimeAttachedDetail(BaseModel):
    """
    任务运行时挂载扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["task_runtime_attached"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar registration_count: 当前任务注册数量。
    :vartype registration_count: int
    :ivar message_bus_attached: 是否已挂载消息总线。
    :vartype message_bus_attached: bool
    :ivar dispatcher_attached: 是否已挂载任务分发器。
    :vartype dispatcher_attached: bool
    :ivar bootstrap_snapshot_attached: 是否已挂载任务装配快照。
    :vartype bootstrap_snapshot_attached: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_runtime_attached"] = TASK_RUNTIME_ATTACHED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    registration_count: int
    message_bus_attached: bool
    dispatcher_attached: bool
    bootstrap_snapshot_attached: bool


class RuntimeAccessorsRefreshedDetail(BaseModel):
    """
    运行时访问器刷新扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["runtime_accessors_refreshed"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar auth_accessor_refreshed: 是否已刷新鉴权访问器。
    :vartype auth_accessor_refreshed: bool
    :ivar logging_accessor_refreshed: 是否已刷新日志访问器。
    :vartype logging_accessor_refreshed: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["runtime_accessors_refreshed"] = RUNTIME_ACCESSORS_REFRESHED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    auth_accessor_refreshed: bool
    logging_accessor_refreshed: bool


class RuntimeResourceStateChangedDetail(BaseModel):
    """
    运行时资源状态变更扩展。

    :ivar kind: 判别联合类型标识。
    :vartype kind: Literal["runtime_resource_state_changed"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar status: 目标运行时资源状态。
    :vartype status: RuntimeResourceStatus
    :ivar detail: 状态诊断详情。
    :vartype detail: str | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["runtime_resource_state_changed"] = RUNTIME_RESOURCE_STATE_CHANGED_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
    status: RuntimeResourceStatus
    detail: str | None = None


RuntimeResourceMountOperationDetail: TypeAlias = Annotated[
    HttpRuntimeAttachedDetail
    | DatabaseRuntimeAttachedDetail
    | LoggingRuntimeAttachedDetail
    | CacheRuntimeAttachedDetail
    | TaskRuntimeAttachedDetail
    | RuntimeAccessorsRefreshedDetail
    | RuntimeResourceStateChangedDetail,
    Field(discriminator="kind"),
]


class RuntimeResourceMountOperationEnvelope(BaseModel):
    """
    运行时资源挂载操作信封。

    :ivar header: 运行时资源挂载操作公共头。
    :vartype header: RuntimeResourceMountOperationHeader
    :ivar detail: 运行时资源挂载操作强类型扩展。
    :vartype detail: RuntimeResourceMountOperationDetail
    """

    model_config = ConfigDict(extra="forbid")

    header: RuntimeResourceMountOperationHeader
    detail: RuntimeResourceMountOperationDetail

    @model_validator(mode="after")
    def validate_mount_operation_contract(
        self,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        校验挂载操作公共头与扩展字段一致。

        :returns: 返回已通过一致性校验的信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        :raises ValueError: 公共头与扩展字段不一致时抛出。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("资源挂载 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("资源挂载 header.schema_version 必须与 detail.schema_version 一致。")
        return self
