"""记录 Codex 浏览器客户端脱敏诊断的应用用例。"""

from __future__ import annotations

from src.application.ports.codex_client_diagnostic_recorder_port import (
    CodexClientDiagnosticRecorderPort,
)
from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticReceipt,
)


class RecordCodexClientDiagnosticUsecase:
    """固定认证主体与诊断信封的应用层记录边界。"""

    def __init__(self, recorder: CodexClientDiagnosticRecorderPort) -> None:
        """
        初始化客户端诊断记录用例。

        :param recorder: 负责二次脱敏、限流与安全日志写入的基础设施端口。
        :type recorder: CodexClientDiagnosticRecorderPort
        """

        self._recorder = recorder

    def execute(
        self,
        *,
        owner_subject_id: str,
        envelope: CodexClientDiagnosticEnvelope,
    ) -> CodexClientDiagnosticReceipt:
        """
        记录已通过 HTTP 契约校验的客户端诊断。

        限流属于诊断的正常降级分支，因此返回回执而非抛出异常，避免可观测性路径
        反向影响用户的实际会话操作。

        :param owner_subject_id: 已认证主体，仅供记录器的瞬时限流键使用。
        :type owner_subject_id: str
        :param envelope: 不含正文、路径、异常栈与认证数据的类型化诊断信封。
        :type envelope: CodexClientDiagnosticEnvelope
        :returns: 当前实例是否已记录安全字段的回执。
        :rtype: CodexClientDiagnosticReceipt
        """

        return self._recorder.record(
            owner_subject_id=owner_subject_id,
            envelope=envelope,
        )
