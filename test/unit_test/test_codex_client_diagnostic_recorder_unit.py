"""Codex 客户端诊断记录器单元测试。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import Mock

from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticDetail,
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticHeader,
    CodexClientDiagnosticSource,
    CodexClientDiagnosticSummary,
)
from src.core.logging_contract.log_event_contract import LogEventEnvelope
from src.infrastructure.codex.codex_client_diagnostic_recorder import (
    CODEX_CLIENT_DIAGNOSTIC_FALLBACK_CODE,
    CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE,
    CodexClientDiagnosticRecorder,
)


class MutableMonotonicClock:
    """为固定窗口边界提供确定性单调时间源。"""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def build_envelope(
    *,
    source: CodexClientDiagnosticSource = CodexClientDiagnosticSource.WINDOW,
    summary: CodexClientDiagnosticSummary = CodexClientDiagnosticSummary.WINDOW_ERROR,
    error_code: str = "client.window.error",
    fingerprint: str = "window:client.window.error",
) -> CodexClientDiagnosticEnvelope:
    """构建不含敏感文本的有效诊断信封。"""

    return CodexClientDiagnosticEnvelope(
        header=CodexClientDiagnosticHeader(
            event_id="diagnostic-test-event",
            source=source,
            occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        ),
        detail=CodexClientDiagnosticDetail(
            summary=summary,
            error_code=error_code,
            fingerprint=fingerprint,
        ),
    )


def test_record_should_limit_each_subject_and_fingerprint_at_twenty_per_minute() -> None:
    """同主体同指纹第 21 条被抑制，窗口边界后恢复接收。"""

    clock = MutableMonotonicClock()
    logger = Mock(spec=logging.Logger)
    emitted_events: list[LogEventEnvelope] = []
    recorder = CodexClientDiagnosticRecorder(
        logger=logger,
        clock=clock,
        log_event_emitter=emitted_events.append,
    )
    envelope = build_envelope()

    receipts = [
        recorder.record(owner_subject_id="subject-a", envelope=envelope)
        for _ in range(CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE + 1)
    ]

    assert all(receipt.recorded for receipt in receipts[:-1])
    assert not receipts[-1].recorded
    assert logger.warning.call_count == 0
    assert len(emitted_events) == CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE

    clock.value = 60.0
    assert recorder.record(owner_subject_id="subject-a", envelope=envelope).recorded


def test_record_should_isolate_subjects_and_sanitize_untrusted_derived_fields() -> None:
    """主体只用于内存键，摘要、代码和指纹均由服务端安全重建。"""

    logger = Mock(spec=logging.Logger)
    emitted_events: list[LogEventEnvelope] = []
    recorder = CodexClientDiagnosticRecorder(
        logger=logger,
        clock=MutableMonotonicClock(),
        log_event_emitter=emitted_events.append,
    )
    envelope = build_envelope(
        summary=CodexClientDiagnosticSummary.VUE_ERROR,
        error_code="request.path-disclosure",
        fingerprint="window:request.path-disclosure",
    )

    first = recorder.record(owner_subject_id="subject-a", envelope=envelope)
    second = recorder.record(owner_subject_id="subject-b", envelope=envelope)

    assert first.recorded
    assert second.recorded
    first_event = emitted_events[0]
    assert first_event.detail.source is CodexClientDiagnosticSource.WINDOW
    assert first_event.detail.summary is CodexClientDiagnosticSummary.WINDOW_ERROR
    assert first_event.detail.error_code == CODEX_CLIENT_DIAGNOSTIC_FALLBACK_CODE
    assert first_event.detail.fingerprint == f"window:{CODEX_CLIENT_DIAGNOSTIC_FALLBACK_CODE}"
    assert first_event.header.authenticated_subject_id is None
    assert "subject-a" not in str(first_event)
    assert "request.path-disclosure" not in str(first_event)
