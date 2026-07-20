"""
契约健康探针API 接口层模块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.application.health_probe_usecase import HealthProbeResult

HEALTH_PROBE_SCHEMA_VERSION = "1.0"
HEALTH_PROBE_KIND = "health_probe"


class HealthProbePayload(BaseModel):
    """
    健康探针Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`HEALTH_PROBE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`HEALTH_PROBE_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar status: 当前状态枚举。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype status: str
    :ivar ready: 运行时是否已经就绪。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype ready: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=HEALTH_PROBE_KIND)
    schema_version: str = Field(default=HEALTH_PROBE_SCHEMA_VERSION)
    status: str
    ready: bool

    @classmethod
    def from_result(cls, result: HealthProbeResult) -> HealthProbePayload:
        """
        处理从结果。

        :param result: 当前流程产出的结果对象。约束：需符合 ``HealthProbeResult`` 注解。
        :type result: HealthProbeResult
        :returns: 返回当前操作结果。
        :rtype: 'HealthProbePayload'
        """

        return cls(
            status=result.status,
            ready=result.ready,
        )
