"""
健康探针用例应用层模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.settings_reader_port import SettingsReaderPort


@dataclass(slots=True)
class HealthProbeResult:
    """
    健康探针数据对象，用于承载当前流程的结构化字段。

    :ivar status: 当前状态枚举。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype status: str
    :ivar ready: 运行时是否已经就绪。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype ready: bool
    :ivar environment: ``environment`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype environment: str
    :ivar version: ``version`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype version: str
    """

    status: str
    ready: bool
    environment: str
    version: str


class HealthProbeUsecase:
    """
    健康探针应用用例，负责封装当前业务流程。
    """

    def __init__(
        self,
        *,
        settings_reader_port: SettingsReaderPort,
    ) -> None:
        """
        初始化健康探针用例。

        :param settings_reader_port: 配置读取端口。
        :type settings_reader_port: SettingsReaderPort
        :returns: 无返回值。
        :rtype: None
        """

        self._settings_reader_port = settings_reader_port

    def execute(self, *, probe_kind: str) -> HealthProbeResult:
        """
        执行健康探针主流程。

        :param probe_kind: 探针类型。约束：需符合 ``str`` 注解。
        :type probe_kind: str
        :returns: 返回当前业务流程产出的结果对象。
        :rtype: HealthProbeResult
        """

        settings_snapshot = self._settings_reader_port.read_health_snapshot()
        ready = settings_snapshot.ready
        if probe_kind == "ready":
            status = "ready" if ready else "starting"
        else:
            status = "alive"
        return HealthProbeResult(
            status=status,
            ready=ready,
            environment=settings_snapshot.environment,
            version=settings_snapshot.version,
        )
