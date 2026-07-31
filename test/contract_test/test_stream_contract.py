"""统一流式公开契约测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from src.api.testing.streaming_test_route_binder import (
    TestStreamControlDetail,
    TestStreamDetail,
    TestStreamItemDetail,
)
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketEnvelope,
    StreamAccessTicketHeader,
    StreamAccessTicketIssuedDetail,
    StreamAccessTicketResultKind,
)
from src.core.stream_contract.stream_control_contract import (
    PingControlDetail,
    StreamClientControlEnvelope,
)
from src.core.stream_contract.stream_delivery_contract import (
    CommandStreamBindingDetail,
    SseDeliveryDetail,
    SseDeliveryMode,
    StreamBatchCompletedDetail,
    StreamBatchEnvelope,
    StreamBatchHeader,
    StreamBatchResultKind,
    StreamDeliveryKind,
    StreamOperationBindingEnvelope,
    StreamOperationBindingHeader,
)
from src.core.stream_contract.stream_event_contract import (
    StreamEventEnvelope,
    StreamEventHeader,
    StreamLifecycleDetail,
    StreamSequenceValidator,
    StreamTransport,
)
from src.core.stream_contract.stream_runtime_contract import StreamRuntimeEnvelope
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment


class TestStreamContract:
    """统一流式契约测试集合。"""

    def test_event_when_header_kind_mismatches_detail_should_reject(self) -> None:
        """验证事件公共头与扩展类型不一致时拒绝。"""

        with pytest.raises(ValidationError):
            StreamEventEnvelope[TestStreamDetail](
                header=StreamEventHeader(
                    stream_id="stream-1",
                    event_id="event-1",
                    sequence=0,
                    event_kind="stream_progress",
                    request_id="request-1",
                    trace_id=None,
                ),
                detail=TestStreamItemDetail(index=0, text="item"),
            )

    def test_event_when_extra_field_present_should_reject(self) -> None:
        """验证业务扩展额外字段被判别联合拒绝。"""

        adapter = TypeAdapter(StreamEventEnvelope[TestStreamDetail])
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {
                    "header": {
                        "stream_id": "stream-1",
                        "event_id": "event-1",
                        "sequence": 0,
                        "event_kind": "test_stream_item",
                        "schema_version": "1.0",
                        "request_id": "request-1",
                        "trace_id": None,
                    },
                    "detail": {
                        "kind": "test_stream_item",
                        "schema_version": "1.0",
                        "index": 0,
                        "text": "item",
                        "extra": True,
                    },
                }
            )

    def test_documented_event_example_should_validate(self) -> None:
        """验证协议文档中的 started 事件示例符合当前 TypeAdapter。"""

        adapter = TypeAdapter(StreamEventEnvelope[StreamLifecycleDetail])
        event = adapter.validate_python(
            {
                "header": {
                    "stream_id": "stream-1",
                    "event_id": "event-1",
                    "sequence": 0,
                    "event_kind": "stream_started",
                    "schema_version": "1.0",
                    "request_id": "request-1",
                    "trace_id": None,
                    "emitted_at": "2026-07-30T10:00:00Z",
                },
                "detail": {
                    "kind": "stream_started",
                    "schema_version": "1.0",
                    "operation_name": "report_generate",
                    "transport": "sse",
                    "resumable": True,
                },
            }
        )

        assert event.header.event_kind == event.detail.kind

    def test_documented_ping_example_should_validate(self) -> None:
        """验证协议文档中的 ping 控制示例符合当前 TypeAdapter。"""

        adapter = TypeAdapter(StreamClientControlEnvelope[PingControlDetail])
        control = adapter.validate_python(
            {
                "header": {
                    "kind": "stream_client_control_header",
                    "schema_version": "1.0",
                    "control_kind": "ping",
                },
                "detail": {
                    "kind": "ping",
                    "schema_version": "1.0",
                    "nonce": "nonce-1",
                },
            }
        )

        assert control.header.control_kind == control.detail.kind

    def test_control_when_unknown_kind_should_reject(self) -> None:
        """验证未知客户端控制类型被拒绝。"""

        adapter = TypeAdapter(StreamClientControlEnvelope[TestStreamControlDetail])
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {
                    "header": {
                        "kind": "stream_client_control_header",
                        "schema_version": "1.0",
                        "control_kind": "unknown",
                    },
                    "detail": {"kind": "unknown", "schema_version": "1.0"},
                }
            )

    def test_complete_control_schema_should_include_subscribe_discriminator(self) -> None:
        """验证完整客户端控制联合冻结 subscribe 判别映射。"""

        schema = TypeAdapter(StreamClientControlEnvelope[TestStreamControlDetail]).json_schema()
        schema_json = json.dumps(schema, ensure_ascii=False, sort_keys=True)

        assert '"discriminator"' in schema_json
        assert '"subscribe"' in schema_json

    def test_event_when_outer_schema_version_mismatches_should_reject(self) -> None:
        """验证事件信封、公共头和扩展三层版本必须一致。"""

        payload = self._build_event().model_dump(mode="json")
        payload["schema_version"] = "2.0"

        with pytest.raises(ValidationError):
            TypeAdapter(StreamEventEnvelope[TestStreamDetail]).validate_python(payload)

    def test_access_ticket_when_header_kind_mismatches_detail_should_reject(self) -> None:
        """验证访问票据公共头与强类型扩展必须一致。"""

        with pytest.raises(ValidationError):
            StreamAccessTicketEnvelope(
                header=StreamAccessTicketHeader(
                    subject_id="subject-1",
                    operation_name="operation-1",
                    result_kind=StreamAccessTicketResultKind.REJECTED,
                ),
                detail=StreamAccessTicketIssuedDetail(
                    ticket="ticket-1",
                    client_ip=None,
                    expires_at=datetime.now(UTC) + timedelta(seconds=30),
                ),
            )

    def test_batch_when_summary_mismatches_terminal_event_should_reject(self) -> None:
        """验证非流式聚合 stream、计数、末序号与终止事件摘要一致。"""

        event = self._build_event()
        with pytest.raises(ValidationError):
            StreamBatchEnvelope[TestStreamDetail](
                header=StreamBatchHeader(
                    stream_id="stream-1",
                    result_kind=StreamBatchResultKind.COMPLETED,
                ),
                detail=StreamBatchCompletedDetail[TestStreamDetail](
                    events=[event],
                    last_sequence=1,
                    event_count=2,
                    total_bytes=1,
                    terminal_event_id="event-1",
                ),
            )

    def test_binding_without_http_transport_should_reject(self) -> None:
        """验证每个流操作必须声明非流式 HTTP 入口。"""

        with pytest.raises(ValidationError):
            StreamOperationBindingEnvelope(
                header=StreamOperationBindingHeader(
                    operation_name="test_operation",
                    delivery_kind=StreamDeliveryKind.COMMAND,
                ),
                detail=CommandStreamBindingDetail(
                    batch_path="/batch",
                    sse_path="/sse",
                    sse_delivery=SseDeliveryDetail(
                        mode=SseDeliveryMode.DUAL,
                        heartbeat_seconds=1,
                        retry_milliseconds=1000,
                        resume_enabled=True,
                        ticket_required=True,
                    ),
                    websocket_path=None,
                    ticket_path="/ticket",
                    websocket_ticket_required=False,
                    transports=frozenset({StreamTransport.SSE}),
                    resumable=True,
                ),
            )

    def test_sequence_validator_should_reject_non_monotonic_sequence(self) -> None:
        """验证序列校验入口拒绝跳号。"""

        validator = StreamSequenceValidator()
        event = StreamEventEnvelope[TestStreamDetail](
            header=StreamEventHeader(
                stream_id="stream-1",
                event_id="event-1",
                sequence=1,
                event_kind="test_stream_item",
                request_id="request-1",
                trace_id=None,
            ),
            detail=TestStreamItemDetail(index=0, text="item"),
        )

        with pytest.raises(ValueError):
            validator.accept(event)

    def _build_event(self) -> StreamEventEnvelope[TestStreamDetail]:
        """构建合法测试业务事件。"""

        return StreamEventEnvelope[TestStreamDetail](
            header=StreamEventHeader(
                stream_id="stream-1",
                event_id="event-1",
                sequence=0,
                event_kind="test_stream_item",
                request_id="request-1",
                trace_id=None,
            ),
            detail=TestStreamItemDetail(index=0, text="item"),
        )

    def test_test_binding_should_register_non_stream_and_stream_paths(self) -> None:
        """验证测试绑定同时注册非流式、SSE 和 WebSocket 路径。"""

        from src.api.testing.test_app_factory import TestAppFactory

        app = TestAppFactory().create()
        paths = {getattr(route, "path", "") for route in app.routes}
        operation_ids = {
            getattr(route, "operation_id", None)
            for route in app.routes
            if getattr(route, "operation_id", None) is not None
        }
        assert "/testing/stream/batch" in paths
        assert "/testing/stream/sse" in paths
        assert "/testing/stream/ws" in paths
        assert "testing_stream_sse_post" in operation_ids
        assert "testing_stream_sse_get" in operation_ids

    @pytest.mark.parametrize(
        "environment",
        [AppEnvironment.DEVELOPMENT, AppEnvironment.TEST, AppEnvironment.PRODUCTION],
    )
    def test_runtime_for_each_environment_should_validate_discriminated_union(
        self,
        environment: AppEnvironment,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证三环境流运行时均通过强类型信封校验。"""

        if environment == AppEnvironment.PRODUCTION:
            monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/app")
            monkeypatch.setenv("REDIS_URL", "redis://:password@redis:6379/0")
            monkeypatch.setenv("RABBITMQ_URL", "amqp://u:p@rabbitmq:5672/%2F")
            monkeypatch.setenv("JWT_SECRET", "production-random-secret-value-2026-xyz")
        settings = AppSettingsLoader().load_for_environment(environment)

        assert isinstance(settings.runtime.stream, StreamRuntimeEnvelope)
        assert settings.runtime.stream.header.mode == settings.runtime.stream.detail.kind
