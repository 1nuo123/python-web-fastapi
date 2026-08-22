"""Codex 客户端诊断记录端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticReceipt,
)


class CodexClientDiagnosticRecorderPort(Protocol):
    """向应用层提供已二次脱敏的客户端诊断记录能力。"""

    def record(
        self,
        *,
        owner_subject_id: str,
        envelope: CodexClientDiagnosticEnvelope,
    ) -> CodexClientDiagnosticReceipt:
        """记录诊断，限流时返回未记录回执且不暴露限流键。"""

        ...
