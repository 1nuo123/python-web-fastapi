"""
契约系统概览API 接口层模块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.application.system_overview_usecase import SystemOverviewResult
from src.core.http_contract.runtime_resource_contract import RuntimeResourceState

SYSTEM_OVERVIEW_SCHEMA_VERSION = "1.0"
SYSTEM_OVERVIEW_PUBLIC_KIND = "system_overview_public"
SYSTEM_OVERVIEW_ADMIN_KIND = "system_overview_admin"


class SystemOverviewPublicPayload(BaseModel):
    """
    系统概览公开载荷，只承载匿名场景允许暴露的最小字段。

    :ivar kind: 公开载荷类型标识。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: str
    :ivar title: 系统概览标题。
    :vartype title: str
    :ivar ready: 运行时是否已经就绪。
    :vartype ready: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=SYSTEM_OVERVIEW_PUBLIC_KIND)
    schema_version: str = Field(default=SYSTEM_OVERVIEW_SCHEMA_VERSION)
    title: str
    ready: bool

    @classmethod
    def from_result(cls, result: SystemOverviewResult) -> SystemOverviewPublicPayload:
        """
        从用例结果构建公开系统概览载荷。

        :param result: 当前流程产出的系统概览结果。
        :type result: SystemOverviewResult
        :returns: 公开系统概览载荷。
        :rtype: SystemOverviewPublicPayload
        """

        return cls(
            title=result.title,
            ready=result.ready,
        )


class SystemOverviewAdminPayload(BaseModel):
    """
    系统概览管理员载荷，用于承载受控可见的运行态摘要。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`SYSTEM_OVERVIEW_ADMIN_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`SYSTEM_OVERVIEW_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar title: 系统概览标题。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype title: str
    :ivar application_name: 应用名称。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype application_name: str
    :ivar version: ``version`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype version: str
    :ivar environment: ``environment`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype environment: str
    :ivar enabled_modules: 启用模块列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype enabled_modules: list[str]
    :ivar ready: 运行时是否已经就绪。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype ready: bool
    :ivar resources: 资源状态集合。约束：需符合 ``list[RuntimeResourceState]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype resources: list[RuntimeResourceState]
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=SYSTEM_OVERVIEW_ADMIN_KIND)
    schema_version: str = Field(default=SYSTEM_OVERVIEW_SCHEMA_VERSION)
    title: str
    application_name: str
    version: str
    environment: str
    enabled_modules: list[str]
    ready: bool
    resources: list[RuntimeResourceState]

    @classmethod
    def from_result(cls, result: SystemOverviewResult) -> SystemOverviewAdminPayload:
        """
        处理从结果。

        :param result: 当前流程产出的结果对象。约束：需符合 ``SystemOverviewResult`` 注解。
        :type result: SystemOverviewResult
        :returns: 返回当前操作结果。
        :rtype: SystemOverviewAdminPayload
        """

        return cls(
            title=result.title,
            application_name=result.application_name,
            version=result.version,
            environment=result.environment,
            enabled_modules=result.enabled_modules,
            ready=result.ready,
            resources=result.resources,
        )
