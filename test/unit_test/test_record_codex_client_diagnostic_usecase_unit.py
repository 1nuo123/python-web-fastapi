"""客户端诊断记录应用用例单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime

from src.application.codex.record_client_diagnostic_usecase import (
    RecordCodexClientDiagnosticUsecase,
)
from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticDetail,
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticHeader,
    CodexClientDiagnosticReceipt,
    CodexClientDiagnosticSource,
    CodexClientDiagnosticSummary,
)


class ClientDiagnosticRecorderFake:
    """记录应用用例传入参数的受控端口替身。"""

    def __init__(self) -> None:
        self.owner_subject_id: str | None = None
        self.envelope: CodexClientDiagnosticEnvelope | None = None

    def record(
        self,
        *,
        owner_subject_id: str,
        envelope: CodexClientDiagnosticEnvelope,
    ) -> CodexClientDiagnosticReceipt:
        """保存调用参数并模拟被限流的正常回执。"""

        self.owner_subject_id = owner_subject_id
        self.envelope = envelope
        return CodexClientDiagnosticReceipt(recorded=False)


def test_execute_should_delegate_authenticated_subject_and_typed_envelope() -> None:
    """应用层不解析或扩展诊断载荷，仅转交基础设施安全边界。"""

    recorder = ClientDiagnosticRecorderFake()
    envelope = CodexClientDiagnosticEnvelope(
        header=CodexClientDiagnosticHeader(
            event_id="diagnostic-usecase-event",
            source=CodexClientDiagnosticSource.PROMISE,
            occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        ),
        detail=CodexClientDiagnosticDetail(
            summary=CodexClientDiagnosticSummary.PROMISE_REJECTION,
            error_code="client.runtime.unclassified",
            fingerprint="promise:client.runtime.unclassified",
        ),
    )

    receipt = RecordCodexClientDiagnosticUsecase(recorder).execute(
        owner_subject_id="subject-a",
        envelope=envelope,
    )

    assert not receipt.recorded
    assert recorder.owner_subject_id == "subject-a"
    assert recorder.envelope is envelope
