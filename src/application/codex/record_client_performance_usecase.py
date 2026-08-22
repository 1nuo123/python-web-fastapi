"""记录 Codex 浏览器客户端性能诊断的应用用例。"""

from __future__ import annotations

from src.application.ports.codex_client_performance_recorder_port import (
    CodexClientPerformanceRecorderPort,
)
from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceReceipt,
)


class RecordCodexClientPerformanceUsecase:
    """固定性能信封与基础设施记录端口之间的应用层边界。"""

    def __init__(self, recorder: CodexClientPerformanceRecorderPort) -> None:
        """
        初始化性能记录用例。

        :param recorder: 负责服务端白名单重建、结构化日志与指标写入的记录端口。
        :type recorder: CodexClientPerformanceRecorderPort
        """

        self._recorder = recorder

    def execute(
        self,
        *,
        envelope: CodexClientPerformanceEnvelope,
    ) -> CodexClientPerformanceReceipt:
        """
        记录已完成 HTTP 契约校验的性能样本。

        样本采集是可观测性旁路，回执只说明当前实例是否接受，不影响会话、认证或重试。

        :param envelope: 不包含正文、路径、异常、用户身份或认证数据的类型化性能信封。
        :type envelope: CodexClientPerformanceEnvelope
        :returns: 当前实例是否写入受限日志与指标的回执。
        :rtype: CodexClientPerformanceReceipt
        """

        return self._recorder.record(envelope=envelope)
