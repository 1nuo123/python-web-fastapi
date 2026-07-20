"""
系统概览用例应用层模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.settings_reader_port import SettingsReaderPort
from src.core.http_contract.runtime_resource_contract import RuntimeResourceState


@dataclass(slots=True)
class SystemOverviewResult:
    """
    系统概览数据对象，用于承载当前流程的结构化字段。

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

    title: str
    application_name: str
    version: str
    environment: str
    enabled_modules: list[str]
    ready: bool
    resources: list[RuntimeResourceState]


class SystemOverviewUsecase:
    """
    系统概览应用用例，负责封装当前业务流程。
    """

    def __init__(
        self,
        *,
        settings_reader_port: SettingsReaderPort,
    ) -> None:
        """
        初始化系统概览用例。

        :param settings_reader_port: 配置读取端口。
        :type settings_reader_port: SettingsReaderPort
        :returns: 无返回值。
        :rtype: None
        """

        self._settings_reader_port = settings_reader_port

    def execute(self) -> SystemOverviewResult:
        """
        执行系统概览主流程。

        :returns: 返回当前业务流程产出的结果对象。
        :rtype: SystemOverviewResult
        """

        settings_snapshot = self._settings_reader_port.read_application_settings_snapshot()
        return SystemOverviewResult(
            title=settings_snapshot.system_overview_title,
            application_name=settings_snapshot.application_name,
            version=settings_snapshot.version,
            environment=settings_snapshot.environment,
            enabled_modules=settings_snapshot.enabled_modules,
            ready=settings_snapshot.ready,
            resources=settings_snapshot.runtime_states,
        )
