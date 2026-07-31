"""测试应用专用强类型流操作绑定。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal, cast

from fastapi import FastAPI, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from src.api.fastapi_stream_route_composer import (
    FastApiStreamRouteComposer,
    StreamOperationBinding,
)
from src.application.ports.stream_event_source_port import StreamExecutionContext
from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.application.streaming.stream_execution_orchestrator import (
    StreamExecutionOrchestrator,
    StreamExecutionPolicy,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.core.stream_contract.stream_access_contract import StreamAccessTicketEnvelope
from src.core.stream_contract.stream_control_contract import (
    CancelControlDetail,
    PingControlDetail,
    ResumeControlDetail,
    StreamClientControlEnvelope,
    SubscribeControlDetail,
)
from src.core.stream_contract.stream_delivery_contract import (
    CommandStreamBindingDetail,
    SseDeliveryDetail,
    SseDeliveryMode,
    StreamCollectionLimit,
    StreamDeliveryKind,
    StreamOperationBindingEnvelope,
    StreamOperationBindingHeader,
)
from src.core.stream_contract.stream_event_contract import (
    StreamCompletedDetail,
    StreamEventEnvelope,
    StreamFaultDetail,
    StreamHeartbeatDetail,
    StreamProgressDetail,
    StreamStartedDetail,
    StreamTransport,
)
from src.infrastructure.streaming.deferred_stream_resources import (
    DeferredStreamSessionRegistry,
    DeferredStreamStateStore,
)
from src.infrastructure.streaming.http_batch_response_presenter import HttpBatchResponsePresenter
from src.infrastructure.streaming.sse_response_presenter import SseResponsePresenter
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec
from src.infrastructure.streaming.websocket_connection_guard import (
    StreamPrincipalSnapshot,
    WebSocketAdmissionPort,
    WebSocketConnectionGuard,
    WebSocketSecurityEventKind,
)
from src.infrastructure.streaming.websocket_session_handler import WebSocketSessionHandler

TEST_STREAM_COMMAND_KIND: Final[Literal["test_stream_command"]] = "test_stream_command"
TEST_STREAM_ITEM_KIND: Final[Literal["test_stream_item"]] = "test_stream_item"
TEST_STREAM_OPERATION_NAME = "testing_stream"
TEST_STREAM_BATCH_PATH = "/testing/stream/batch"
TEST_STREAM_SSE_PATH = "/testing/stream/sse"
TEST_STREAM_WEBSOCKET_PATH = "/testing/stream/ws"
TEST_STREAM_TICKET_PATH = "/testing/stream/ticket"
TEST_STREAM_BEARER_TOKEN = "test-stream-token"
TEST_STREAM_EXPIRING_BEARER_TOKEN = "test-stream-expiring-token"
TEST_STREAM_SUBJECT_ID = "test-stream-subject"


class TestStreamCommand(BaseModel):
    """测试流命令。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["test_stream_command"] = TEST_STREAM_COMMAND_KIND
    schema_version: Literal["1.0"] = "1.0"
    count: int = Field(ge=0, le=16)
    delay_milliseconds: int = Field(default=0, ge=0, le=100)
    fail_after_events: int | None = Field(default=None, ge=0, le=16)
    __test__ = False


class TestStreamItemDetail(BaseModel):
    """测试流业务事件。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["test_stream_item"] = TEST_STREAM_ITEM_KIND
    schema_version: Literal["1.0"] = "1.0"
    index: int = Field(ge=0)
    text: str
    __test__ = False


TestStreamDetail = Annotated[
    StreamStartedDetail
    | StreamProgressDetail
    | StreamHeartbeatDetail
    | StreamCompletedDetail
    | StreamFaultDetail
    | TestStreamItemDetail,
    Field(discriminator="kind"),
]
TestStreamControlDetail = Annotated[
    SubscribeControlDetail[TestStreamCommand]
    | ResumeControlDetail
    | CancelControlDetail
    | PingControlDetail,
    Field(discriminator="kind"),
]


class TestStreamEventSource:
    """确定性测试流事件源。"""

    async def open(
        self,
        *,
        command: TestStreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncGenerator[TestStreamDetail, None]:
        """按命令产生测试业务事件。"""

        for index in range(command.count):
            if command.fail_after_events == index:
                raise RuntimeError("测试流事件源按命令触发失败。")
            if command.delay_milliseconds > 0:
                await asyncio.sleep(command.delay_milliseconds / 1000)
            yield TestStreamItemDetail(index=index, text=f"测试事件-{index}")
        if command.fail_after_events == command.count:
            raise RuntimeError("测试流事件源按命令触发失败。")


class TestWebSocketAdmissionPort(WebSocketAdmissionPort):
    """测试应用专用静态准入端口。"""

    async def authenticate_bearer(self, *, token: str) -> StreamPrincipalSnapshot:
        """认证固定测试 Bearer。"""

        if token == TEST_STREAM_EXPIRING_BEARER_TOKEN:
            return self._build_principal(
                TEST_STREAM_SUBJECT_ID,
                expires_after=timedelta(milliseconds=100),
            )
        if token != TEST_STREAM_BEARER_TOKEN:
            raise PermissionError("测试 Bearer 无效。")
        return self._build_principal(TEST_STREAM_SUBJECT_ID)

    async def load_ticket_subject(self, *, subject_id: str) -> StreamPrincipalSnapshot:
        """读取固定测试主体。"""

        if subject_id != TEST_STREAM_SUBJECT_ID:
            raise PermissionError("测试票据主体无效。")
        return self._build_principal(subject_id)

    async def assert_operation_allowed(
        self,
        *,
        principal: StreamPrincipalSnapshot,
        operation_name: str,
    ) -> None:
        """断言测试主体可访问固定操作。"""

        if operation_name != TEST_STREAM_OPERATION_NAME:
            raise PermissionError("测试主体无权访问目标流操作。")

    async def assert_ip_allowed(
        self,
        *,
        websocket: WebSocket,
        client_ip: str,
    ) -> None:
        """测试环境允许全部非空客户端 IP。"""

        if client_ip.strip() == "":
            raise PermissionError("测试客户端 IP 为空。")

    async def assert_rate_limit(
        self,
        *,
        websocket: WebSocket,
        principal: StreamPrincipalSnapshot,
        client_ip: str,
        operation_name: str,
    ) -> None:
        """测试环境由会话注册表执行连接配额。"""

    async def record_security_event(
        self,
        *,
        event_kind: WebSocketSecurityEventKind,
        operation_name: str,
        reason: str,
    ) -> None:
        """测试准入端口接收低基数安全事件。"""

    def _build_principal(
        self,
        subject_id: str,
        *,
        expires_after: timedelta = timedelta(hours=1),
    ) -> StreamPrincipalSnapshot:
        """构建测试主体快照。"""

        return StreamPrincipalSnapshot(
            subject_id=subject_id,
            roles=frozenset({"tester"}),
            scopes=frozenset({"stream:test"}),
            credential_expires_at=datetime.now(UTC) + expires_after,
        )


class StreamingTestRouteBinder:
    """只在测试应用中注册统一流操作。"""

    def __init__(self, app: FastAPI) -> None:
        """初始化测试流路由绑定器。"""

        self._app = app
        resource_mount = app.state.container.resource_mount
        self._resource_mount = resource_mount
        self._state_store = DeferredStreamStateStore(
            resources_provider=resource_mount.get_streaming_resources,
        )
        self._session_registry = DeferredStreamSessionRegistry(
            resources_provider=resource_mount.get_streaming_resources,
        )
        self._ticket_service = StreamAccessTicketService(
            state_store=self._state_store,
            ttl_seconds=30,
        )

    def bind(self) -> None:
        """绑定非流式、SSE、WebSocket 与票据测试入口。"""

        event_adapter = TypeAdapter(StreamEventEnvelope[TestStreamDetail])
        control_adapter = TypeAdapter(StreamClientControlEnvelope[TestStreamControlDetail])
        codec = StreamEventCodec(
            adapter=event_adapter,
            max_event_bytes=16384,
        )
        orchestrator: StreamExecutionOrchestrator[TestStreamCommand, TestStreamDetail] = (
            StreamExecutionOrchestrator(
                event_adapter=event_adapter,
                policy=StreamExecutionPolicy(
                    queue_capacity=4,
                    send_timeout_seconds=0.5,
                    max_duration_seconds=5.0,
                    max_event_bytes=16384,
                ),
            )
        )
        binding = StreamOperationBinding(
            contract=StreamOperationBindingEnvelope(
                header=StreamOperationBindingHeader(
                    operation_name=TEST_STREAM_OPERATION_NAME,
                    delivery_kind=StreamDeliveryKind.COMMAND,
                ),
                detail=CommandStreamBindingDetail(
                    batch_path=TEST_STREAM_BATCH_PATH,
                    sse_path=TEST_STREAM_SSE_PATH,
                    sse_delivery=SseDeliveryDetail(
                        mode=SseDeliveryMode.DUAL,
                        heartbeat_seconds=1,
                        retry_milliseconds=1000,
                        resume_enabled=True,
                        ticket_required=True,
                    ),
                    websocket_path=TEST_STREAM_WEBSOCKET_PATH,
                    ticket_path=None,
                    websocket_ticket_required=False,
                    transports=frozenset(
                        {
                            StreamTransport.HTTP,
                            StreamTransport.SSE,
                            StreamTransport.WEBSOCKET,
                        }
                    ),
                    resumable=True,
                ),
            ),
            command_adapter=TypeAdapter(TestStreamCommand),
            event_adapter=event_adapter,
            control_adapter=control_adapter,
            source=TestStreamEventSource(),
            orchestrator=orchestrator,
            codec=codec,
            batch_presenter=HttpBatchResponsePresenter(response_factory=ResponseEnvelopeFactory()),
            sse_presenter=SseResponsePresenter(
                codec=codec,
                heartbeat_seconds=1,
                retry_milliseconds=1000,
                send_timeout_seconds=0.5,
            ),
            websocket_guard=WebSocketConnectionGuard(
                allowed_origins=frozenset({"http://testserver"}),
                require_browser_ticket=False,
                admission_port=TestWebSocketAdmissionPort(),
                ticket_service=self._ticket_service,
                session_registry=self._session_registry,
            ),
            websocket_handler=WebSocketSessionHandler(
                command_adapter=TypeAdapter(TestStreamCommand),
                control_adapter=control_adapter,
                orchestrator=orchestrator,
                codec=codec,
                state_store=self._state_store,
                max_message_bytes=8192,
                send_timeout_seconds=0.5,
                replay_ttl_seconds=30,
                replay_max_events=32,
                max_duration_seconds=5.0,
                runtime_provider=self._resource_mount.get_stream_runtime,
            ),
            ticket_service=self._ticket_service,
            state_store=self._state_store,
            collection_limit=StreamCollectionLimit(
                max_events=32,
                max_bytes=131072,
                timeout_seconds=2.0,
            ),
            replay_ttl_seconds=30,
            replay_max_events=32,
            max_duration_seconds=5.0,
            session_registry=self._session_registry,
            require_authenticated=False,
            runtime_provider=self._resource_mount.get_stream_runtime,
        )
        FastApiStreamRouteComposer().compose(
            app=self._app,
            bindings=cast(
                list[StreamOperationBinding[BaseModel, BaseModel, BaseModel]],
                [binding],
            ),
        )
        self._app.add_api_route(
            TEST_STREAM_TICKET_PATH,
            self.issue_ticket,
            methods=["POST"],
            operation_id="testing_stream_ticket",
        )

    async def issue_ticket(self, request: Request) -> StreamAccessTicketEnvelope:
        """签发测试 WebSocket 单次票据。"""

        client_ip = request.client.host if request.client is not None else "unknown"
        return await self._ticket_service.issue(
            subject_id=TEST_STREAM_SUBJECT_ID,
            operation_name=TEST_STREAM_OPERATION_NAME,
            client_ip=client_ip,
        )
