"""客户端性能记录用例的隔离单元测试。"""

from datetime import UTC, datetime
from unittest.mock import Mock

from src.application.codex.record_client_performance_usecase import (
    RecordCodexClientPerformanceUsecase,
)
from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceDetail,
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceHeader,
    CodexClientPerformanceMetric,
    CodexClientPerformanceObservation,
    CodexClientPerformanceReceipt,
    CodexClientPerformanceUnit,
)


def test_execute_should_delegate_only_the_typed_performance_envelope() -> None:
    """应用层不增加身份、正文或传输副作用，只委托记录端口。"""

    recorder = Mock()
    recorder.record.return_value = CodexClientPerformanceReceipt(recorded=True)
    usecase = RecordCodexClientPerformanceUsecase(recorder=recorder)
    envelope = CodexClientPerformanceEnvelope(
        header=CodexClientPerformanceHeader(
            event_id="performance-usecase-test",
            occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        ),
        detail=CodexClientPerformanceDetail(
            metric=CodexClientPerformanceMetric.REALTIME_BATCH_EVENT_COUNT,
            observation=CodexClientPerformanceObservation.NORMAL_BATCH,
            unit=CodexClientPerformanceUnit.COUNT,
            value=3,
        ),
    )

    receipt = usecase.execute(envelope=envelope)

    assert receipt.recorded
    recorder.record.assert_called_once_with(envelope=envelope)
