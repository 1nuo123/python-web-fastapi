"""
请求作用域契约核心契约模块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

REQUEST_SCOPE_SCHEMA_VERSION = "1.0"
REQUEST_SCOPE_KIND = "request_scope"


class RequestScope(BaseModel):
    """
    请求作用域Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`REQUEST_SCOPE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`REQUEST_SCOPE_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar request_id: 请求唯一标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype request_id: str
    :ivar trace_id: 链路追踪标识。约束：需符合 ``str | None`` 注解；允许为空值。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype trace_id: str | None
    :ivar request_time_epoch: 请求开始时间戳。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达 Unix 时间戳秒值。
    :vartype request_time_epoch: int
    :ivar request_path: 请求路径。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype request_path: str
    :ivar request_method: 请求方法。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype request_method: str
    :ivar authenticated_subject_id: 已认证主体标识。约束：需符合 ``str | None`` 注解；允许为空值。默认值：`None`。取值语义：用于唯一标识对应实体。
    :vartype authenticated_subject_id: str | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=REQUEST_SCOPE_KIND)
    schema_version: str = Field(default=REQUEST_SCOPE_SCHEMA_VERSION)
    request_id: str
    trace_id: str | None
    request_time_epoch: int
    request_path: str
    request_method: str
    authenticated_subject_id: str | None = None
