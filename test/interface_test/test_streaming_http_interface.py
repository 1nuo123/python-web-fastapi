"""统一流式 HTTP 与 SSE 接口测试。"""

from __future__ import annotations

import json
from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BATCH_PATH,
    TEST_STREAM_COMMAND_KIND,
    TEST_STREAM_SSE_PATH,
    TEST_STREAM_TICKET_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.settings.application_settings import AppEnvironment

CONTENT_TYPE_HEADER = "content-type"
CACHE_CONTROL_HEADER = "cache-control"
ACCEL_BUFFERING_HEADER = "x-accel-buffering"
STREAM_TICKET_QUERY_NAME = "ticket"
STREAM_TICKET_SUBJECT_QUERY_NAME = "subject_id"
SSE_COMMAND_QUERY_NAME = "command"


class TestStreamingHttpInterface:
    """统一流式 HTTP 与 SSE 接口测试集合。"""

    def test_batch_should_return_lifecycle_and_business_events_in_order(self) -> None:
        """验证非流式入口返回同一事件源的有序聚合结果。"""

        with TestClient(TestAppFactory().create()) as client:
            response = client.post(TEST_STREAM_BATCH_PATH, json=self._build_command(2))

        assert response.status_code == HTTPStatus.OK
        payload = response.json()
        events = payload["data"]["detail"]["events"]
        assert [event["header"]["sequence"] for event in events] == [0, 1, 2, 3]
        assert [event["detail"]["kind"] for event in events] == [
            "stream_started",
            "test_stream_item",
            "test_stream_item",
            "stream_completed",
        ]

    def test_sse_should_return_required_headers_and_event_fields(self) -> None:
        """验证 SSE 响应头与 id/event/data 映射。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.stream(
                "POST",
                TEST_STREAM_SSE_PATH,
                json=self._build_command(1),
            ) as response:
                lines = [line for line in response.iter_lines() if line]

        assert response.status_code == HTTPStatus.OK
        assert response.headers[CONTENT_TYPE_HEADER].startswith("text/event-stream")
        assert response.headers[CACHE_CONTROL_HEADER] == "no-cache, no-transform"
        assert response.headers[ACCEL_BUFFERING_HEADER] == "no"
        assert any(line.startswith("id: ") for line in lines)
        assert any(line == "event: test_stream_item" for line in lines)
        data_line = next(line for line in lines if line.startswith("data: "))
        assert "header" in json.loads(data_line.removeprefix("data: "))

    def test_sse_when_resume_parameters_incomplete_should_reject(self) -> None:
        """验证 SSE 恢复参数必须成对提供。"""

        with TestClient(TestAppFactory().create()) as client:
            response = client.post(
                f"{TEST_STREAM_SSE_PATH}?stream_id=stream-only",
                json=self._build_command(1),
            )

        assert response.status_code >= HTTPStatus.BAD_REQUEST

    def test_native_event_source_should_consume_single_use_ticket(self) -> None:
        """验证 native EventSource 通过 GET 原子消费短期单次票据。"""

        with TestClient(TestAppFactory().create()) as client:
            ticket_payload = client.post(TEST_STREAM_TICKET_PATH).json()
            query = {
                STREAM_TICKET_QUERY_NAME: ticket_payload["detail"][STREAM_TICKET_QUERY_NAME],
                STREAM_TICKET_SUBJECT_QUERY_NAME: ticket_payload["header"][
                    STREAM_TICKET_SUBJECT_QUERY_NAME
                ],
                SSE_COMMAND_QUERY_NAME: json.dumps(
                    self._build_command(1),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
            with client.stream("GET", TEST_STREAM_SSE_PATH, params=query) as response:
                lines = [line for line in response.iter_lines() if line]
            repeated_response = client.get(TEST_STREAM_SSE_PATH, params=query)

        assert response.status_code == HTTPStatus.OK
        assert any(line == "event: test_stream_item" for line in lines)
        assert repeated_response.status_code == HTTPStatus.FORBIDDEN
        assert repeated_response.json()["data"]["error_code"] == ("system.stream.ticket_invalid")

    def test_sse_resume_should_replay_events_after_last_event_id(self) -> None:
        """验证 SSE 在有限窗口内从最后事件之后继续。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.stream(
                "POST",
                TEST_STREAM_SSE_PATH,
                json=self._build_command(2),
            ) as first_response:
                first_payloads = [
                    json.loads(line.removeprefix("data: "))
                    for line in first_response.iter_lines()
                    if line.startswith("data: ")
                ]
            first_item = next(
                payload
                for payload in first_payloads
                if payload["detail"]["kind"] == "test_stream_item"
            )
            stream_id = first_item["header"]["stream_id"]
            event_id = first_item["header"]["event_id"]
            with client.stream(
                "POST",
                f"{TEST_STREAM_SSE_PATH}?stream_id={stream_id}",
                headers={"Last-Event-ID": event_id},
                json=self._build_command(0),
            ) as resumed_response:
                resumed_payloads = [
                    json.loads(line.removeprefix("data: "))
                    for line in resumed_response.iter_lines()
                    if line.startswith("data: ")
                ]

        assert resumed_payloads[0]["header"]["stream_id"] == stream_id
        assert resumed_payloads[0]["header"]["sequence"] > first_item["header"]["sequence"]

    def test_sse_new_connection_after_hot_reload_should_use_new_retry_value(self) -> None:
        """验证热更新后新 SSE 连接真实读取新的 retry 配置。"""

        app = TestAppFactory().create()
        with TestClient(app) as client:
            result = app.state.container.reload_coordinator.reload_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"stream": {"detail": {"sse_retry_milliseconds": 2000}}}},
            )
            with client.stream(
                "POST",
                TEST_STREAM_SSE_PATH,
                json=self._build_command(0),
            ) as response:
                lines = list(response.iter_lines())

        assert result.success is True
        assert "retry: 2000" in lines

    def test_sse_long_running_stream_should_emit_comment_heartbeat(self) -> None:
        """验证真实心跳使用注释帧且不污染业务 sequence。"""

        command = self._build_command(16)
        command["delay_milliseconds"] = 100
        with TestClient(TestAppFactory().create()) as client:
            with client.stream("POST", TEST_STREAM_SSE_PATH, json=command) as response:
                lines = list(response.iter_lines())

        assert ": heartbeat" in lines

    def test_sse_when_resume_event_id_forged_should_reject_before_response_start(self) -> None:
        """验证伪造恢复事件 ID 在 SSE 响应启动前被拒绝。"""

        with TestClient(TestAppFactory().create()) as client:
            response = client.post(
                f"{TEST_STREAM_SSE_PATH}?stream_id=forged-stream",
                headers={"Last-Event-ID": "forged-event"},
                json=self._build_command(0),
            )

        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json()["data"]["error_code"] == "system.stream.replay_unavailable"

    def _build_command(self, count: int) -> dict[str, object]:
        """构建测试流命令。"""

        return {
            "kind": TEST_STREAM_COMMAND_KIND,
            "schema_version": "1.0",
            "count": count,
            "delay_milliseconds": 0,
        }
