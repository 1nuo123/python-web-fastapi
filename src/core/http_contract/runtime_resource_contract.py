"""
运行时资源契约核心契约模块。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

RUNTIME_RESOURCE_SCHEMA_VERSION = "1.0"
RUNTIME_RESOURCE_STATE_KIND = "runtime_resource_state"
TELEMETRY_BRIDGE_STATE_KIND = "telemetry_bridge_state"


class RuntimeResourceStatus(StrEnum):
    """
    运行时资源状态枚举，用于约束可选取值。

    :cvar CREATED: ``CREATED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'created'`。取值语义：用于承载当前对象中的业务状态。
    :vartype CREATED: str
    :cvar STARTING: ``STARTING`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'starting'`。取值语义：用于承载当前对象中的业务状态。
    :vartype STARTING: str
    :cvar READY: ``READY`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'ready'`。取值语义：用于承载当前对象中的业务状态。
    :vartype READY: str
    :cvar FAILED: ``FAILED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'failed'`。取值语义：用于承载当前对象中的业务状态。
    :vartype FAILED: str
    :cvar STOPPING: ``STOPPING`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'stopping'`。取值语义：用于承载当前对象中的业务状态。
    :vartype STOPPING: str
    :cvar STOPPED: ``STOPPED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'stopped'`。取值语义：用于承载当前对象中的业务状态。
    :vartype STOPPED: str
    """

    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


class RuntimeResourceState(BaseModel):
    """
    运行时资源状态Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`RUNTIME_RESOURCE_STATE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`RUNTIME_RESOURCE_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar resource_name: ``resource_name`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype resource_name: str
    :ivar status: 当前状态枚举。约束：需符合 ``RuntimeResourceStatus`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype status: RuntimeResourceStatus
    :ivar detail: 诊断详情。约束：需符合 ``str | None`` 注解；允许为空值。默认值：`None`。取值语义：用于承载当前对象中的业务状态。
    :vartype detail: str | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=RUNTIME_RESOURCE_STATE_KIND)
    schema_version: str = Field(default=RUNTIME_RESOURCE_SCHEMA_VERSION)
    resource_name: str
    status: RuntimeResourceStatus
    detail: str | None = None


class TelemetryBridgeState(BaseModel):
    """
    遥测桥接器状态Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`TELEMETRY_BRIDGE_STATE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`RUNTIME_RESOURCE_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar enabled: 功能是否启用。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示启用，``False`` 表示关闭。
    :vartype enabled: bool
    :ivar no_op: ``no_op`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype no_op: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=TELEMETRY_BRIDGE_STATE_KIND)
    schema_version: str = Field(default=RUNTIME_RESOURCE_SCHEMA_VERSION)
    enabled: bool
    no_op: bool
