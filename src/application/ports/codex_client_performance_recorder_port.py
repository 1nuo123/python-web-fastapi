"""Codex 客户端性能诊断记录端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceReceipt,
)


class CodexClientPerformanceRecorderPort(Protocol):
    """向应用层提供服务端白名单收敛后的性能样本记录能力。"""

    def record(
        self,
        *,
        envelope: CodexClientPerformanceEnvelope,
    ) -> CodexClientPerformanceReceipt:
        """记录性能样本，禁止持久化任何浏览器身份或正文。"""

        ...
