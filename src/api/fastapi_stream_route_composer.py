"""FastAPI 统一流操作路由组合器。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from http import HTTPStatus
from typing import Generic, TypeVar

from fastapi import FastAPI, Request, WebSocket
from pydantic import BaseModel, TypeAdapter

from src.api.streaming_context_accessor import (
    StreamingContextAccessor,
    StreamRequestIdentity,
)
from src.application.authorization_guard import AuthorizationGuard
from src.application.ports.stream_event_source_port import (
    StreamEventSourcePort,
    StreamExecutionContext,
)
from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.application.streaming.stream_execution_orchestrator import (
    StreamExecutionOrchestrator,
    StreamExecutionPolicy,
    StreamQueueSaturationObserverPort,
)
from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.authorization_policy_contract import RouteAuthorizationRequirement
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.stream_contract.stream_access_contract import (
    StreamReplayEventRecord,
    StreamResumeRequest,
)
from src.core.stream_contract.stream_control_contract import StreamClientControlEnvelope
from src.core.stream_contract.stream_delivery_contract import (
    SseDeliveryMode,
    SseResumeRequest,
    StreamBatchCompletedDetail,
    StreamBatchRejectedDetail,
    StreamCollectionLimit,
    StreamOperationBindingEnvelope,
)
from src.core.stream_contract.stream_event_contract import (
    STREAM_SCHEMA_VERSION,
    StreamCloseReason,
    StreamCompletedDetail,
    StreamEventEnvelope,
    StreamEventHeader,
    StreamFaultDetail,
    StreamTransport,
)
from src.core.stream_contract.stream_runtime_contract import StreamRuntimeEnvelope
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
    StreamEventMetric,
    StreamMetricEventKind,
    StreamMetricOutcome,
    StreamResumeMetric,
)
from src.infrastructure.orjson_document_response import OrjsonDocumentResponse
from src.infrastructure.streaming.http_batch_response_presenter import HttpBatchResponsePresenter
from src.infrastructure.streaming.sse_response_presenter import SseResponsePresenter
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec
from src.infrastructure.streaming.stream_observation import (
    STREAM_ACCESS_OBSERVATION_STATE_KEY,
    StreamAccessObservation,
)
from src.infrastructure.streaming.stream_session_registry import (
    StreamSessionAdmissionError,
    StreamSessionIdentity,
    StreamSessionLease,
    StreamSessionRegistryPort,
)
from src.infrastructure.streaming.websocket_connection_guard import WebSocketConnectionGuard
from src.infrastructure.streaming.websocket_session_handler import WebSocketSessionHandler

LAST_EVENT_ID_HEADER = "last-event-id"
STREAM_ID_QUERY_NAME = "stream_id"
HTTP_BATCH_METHODS = ["POST"]
STREAM_TICKET_METHODS = ["POST"]
SSE_POST_METHODS = ["POST"]
SSE_GET_METHODS = ["GET"]
HTTP_GET_METHOD = "GET"
SSE_COMMAND_QUERY_NAME = "command"
STREAM_TICKET_QUERY_NAME = "ticket"
STREAM_TICKET_SUBJECT_QUERY_NAME = "subject_id"
STREAM_REPLAY_WRITE_FAILED_MESSAGE = "流事件恢复窗口写入失败，当前实时发送继续且恢复能力已关闭。"
STREAM_REPLAY_INVALID_MESSAGE = "SSE 恢复窗口已过期、无权访问或事件内容无效。"
STREAM_SERVICE_SHUTDOWN_MESSAGE = "服务正在停机，流会话即将关闭。"
STREAM_SESSION_UNAVAILABLE_MESSAGE = "流会话当前无法建立。"
STREAM_SUBJECT_DIGEST_ENCODING = "utf-8"

T_StreamCommand = TypeVar("T_StreamCommand", bound=BaseModel)
T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)
T_StreamControl = TypeVar("T_StreamControl", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StreamOperationBinding(Generic[T_StreamCommand, T_StreamDetail, T_StreamControl]):
    """可执行流操作绑定。"""

    contract: StreamOperationBindingEnvelope
    command_adapter: TypeAdapter[T_StreamCommand]
    event_adapter: TypeAdapter[StreamEventEnvelope[T_StreamDetail]]
    control_adapter: TypeAdapter[StreamClientControlEnvelope[T_StreamControl]]
    source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail]
    orchestrator: StreamExecutionOrchestrator[T_StreamCommand, T_StreamDetail]
    codec: StreamEventCodec[T_StreamDetail]
    batch_presenter: HttpBatchResponsePresenter[T_StreamDetail]
    sse_presenter: SseResponsePresenter[T_StreamDetail]
    websocket_guard: WebSocketConnectionGuard | None
    websocket_handler: (
        WebSocketSessionHandler[T_StreamCommand, T_StreamDetail, T_StreamControl] | None
    )
    ticket_service: StreamAccessTicketService | None
    state_store: StreamStateStorePort
    collection_limit: StreamCollectionLimit
    replay_ttl_seconds: int
    replay_max_events: int
    max_duration_seconds: float
    session_registry: StreamSessionRegistryPort
    require_authenticated: bool
    authorization_requirement: RouteAuthorizationRequirement | None = None
    authorization_guard: AuthorizationGuard | None = None
    metrics_registry: PrometheusMetricsRegistry | None = None
    runtime_provider: Callable[[], StreamRuntimeEnvelope] | None = None
    queue_saturation_observer: StreamQueueSaturationObserverPort | None = None


class FastApiStreamRouteComposer:
    """成对注册非流式、SSE 与 WebSocket 流操作入口。"""

    def __init__(self, *, context_accessor: StreamingContextAccessor | None = None) -> None:
        """初始化路由组合器。"""

        self._context_accessor = context_accessor or StreamingContextAccessor()
        self._logger = logging.getLogger(__name__)

    def compose(
        self,
        *,
        app: FastAPI,
        bindings: list[StreamOperationBinding[BaseModel, BaseModel, BaseModel]],
    ) -> None:
        """校验并注册全部流操作绑定。

        :param app: FastAPI 应用。
        :type app: FastAPI
        :param bindings: 流操作绑定集合。
        :type bindings: list[StreamOperationBinding[BaseModel, BaseModel, BaseModel]]
        :raises ValueError: 路径、操作名或路由标识重复时抛出。
        """

        self._validate_bindings(app=app, bindings=bindings)
        for binding in bindings:
            detail = binding.contract.detail
            operation_name = binding.contract.header.operation_name

            async def batch_route(
                request: Request,
                current_binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel] = binding,
            ) -> OrjsonDocumentResponse:
                return await self.deliver_batch(request, binding=current_binding)

            setattr(
                batch_route,
                "__signature__",
                inspect.Signature(
                    parameters=[
                        inspect.Parameter(
                            "request",
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=Request,
                        )
                    ],
                ),
            )

            app.add_api_route(
                detail.batch_path,
                batch_route,
                methods=HTTP_BATCH_METHODS,
                operation_id=f"{operation_name}_batch",
                name=f"{operation_name}_batch",
            )
            if detail.ticket_path is not None:
                if binding.ticket_service is None:
                    raise ValueError("声明流访问票据路径时必须提供票据服务。")

                async def ticket_route(
                    request: Request,
                    current_binding: StreamOperationBinding[
                        BaseModel, BaseModel, BaseModel
                    ] = binding,
                ) -> OrjsonDocumentResponse:
                    return await self.deliver_ticket(request, binding=current_binding)

                setattr(
                    ticket_route,
                    "__signature__",
                    inspect.Signature(
                        parameters=[
                            inspect.Parameter(
                                "request",
                                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=Request,
                            )
                        ],
                    ),
                )
                app.add_api_route(
                    detail.ticket_path,
                    ticket_route,
                    methods=STREAM_TICKET_METHODS,
                    operation_id=f"{operation_name}_ticket",
                    name=f"{operation_name}_ticket",
                )
            if detail.sse_path is not None:
                if detail.sse_delivery is None:
                    raise ValueError("SSE 路径必须声明强类型交付扩展。")
                native_event_source_enabled = detail.sse_delivery.mode in {
                    SseDeliveryMode.TICKET_GET,
                    SseDeliveryMode.DUAL,
                }
                if native_event_source_enabled and binding.ticket_service is None:
                    raise ValueError("native EventSource 交付必须提供单次票据服务。")

                async def sse_route(
                    request: Request,
                    current_binding: StreamOperationBinding[
                        BaseModel, BaseModel, BaseModel
                    ] = binding,
                ) -> object:
                    return await self.deliver_sse(request, binding=current_binding)

                setattr(
                    sse_route,
                    "__signature__",
                    inspect.Signature(
                        parameters=[
                            inspect.Parameter(
                                "request",
                                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=Request,
                            )
                        ],
                    ),
                )

                if detail.sse_delivery.mode in {
                    SseDeliveryMode.BEARER_POST,
                    SseDeliveryMode.DUAL,
                }:
                    app.add_api_route(
                        detail.sse_path,
                        sse_route,
                        methods=SSE_POST_METHODS,
                        operation_id=f"{operation_name}_sse_post",
                        name=f"{operation_name}_sse_post",
                    )
                if native_event_source_enabled:
                    app.add_api_route(
                        detail.sse_path,
                        sse_route,
                        methods=SSE_GET_METHODS,
                        operation_id=f"{operation_name}_sse_get",
                        name=f"{operation_name}_sse_get",
                    )
            if detail.websocket_path is not None:
                if binding.websocket_guard is None or binding.websocket_handler is None:
                    raise ValueError("声明 WebSocket 交付时必须提供准入守卫和会话处理器。")

                async def websocket_route(
                    websocket: WebSocket,
                    current_binding: StreamOperationBinding[
                        BaseModel, BaseModel, BaseModel
                    ] = binding,
                ) -> None:
                    await self.deliver_websocket(websocket, binding=current_binding)

                setattr(
                    websocket_route,
                    "__signature__",
                    inspect.Signature(
                        parameters=[
                            inspect.Parameter(
                                "websocket",
                                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=WebSocket,
                            )
                        ],
                    ),
                )

                app.add_api_websocket_route(
                    detail.websocket_path,
                    websocket_route,
                    name=f"{operation_name}_websocket",
                )

    async def deliver_batch(
        self,
        request: Request,
        *,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> OrjsonDocumentResponse:
        """交付非流式聚合响应。"""

        identity = self._context_accessor.read_http(
            request,
            require_authenticated=binding.require_authenticated,
        )
        self._authorize_http(request=request, binding=binding)
        command = binding.command_adapter.validate_json(await request.body())
        now = datetime.now(UTC)
        context = StreamExecutionContext(
            request_id=identity.request_id,
            trace_id=identity.trace_id,
            subject_id=identity.subject_id,
            client_ip=identity.client_ip,
            operation_name=binding.contract.header.operation_name,
            transport=StreamTransport.HTTP,
            resumable=binding.contract.detail.resumable,
            deadline=now + timedelta(seconds=binding.max_duration_seconds),
        )
        batch = await self._resolve_orchestrator(binding).collect(
            source=binding.source,
            command=command,
            context=context,
            limit=binding.collection_limit,
        )
        batch_observation = self._create_observation(
            operation_name=binding.contract.header.operation_name,
            transport=StreamTransport.HTTP,
            subject_id=identity.subject_id,
        )
        batch_observation.event_count = batch.detail.event_count
        batch_observation.close_reason = (
            batch.detail.close_reason
            if isinstance(batch.detail, StreamBatchRejectedDetail)
            else StreamCloseReason.COMPLETED
        )
        request.scope["state"][STREAM_ACCESS_OBSERVATION_STATE_KEY] = batch_observation
        if binding.metrics_registry is not None and isinstance(
            batch.detail, StreamBatchCompletedDetail
        ):
            for event in batch.detail.events:
                binding.metrics_registry.record_stream_event(
                    StreamEventMetric(
                        transport=StreamTransport.HTTP,
                        event_kind=StreamMetricEventKind.resolve(event.header.event_kind),
                        byte_count=len(binding.codec.encode(event)),
                    )
                )
        request_scope = getattr(request.state, "request_scope", None)
        if not isinstance(request_scope, RequestScope):
            request_scope = RequestScope(
                request_id=identity.request_id,
                trace_id=identity.trace_id,
                request_time_epoch=int(datetime.now(UTC).timestamp()),
                request_path=request.url.path,
                request_method=request.method,
                authenticated_subject_id=identity.subject_id,
            )
        envelope = binding.batch_presenter.present(
            request_scope=request_scope,
            batch=batch,
        )
        return OrjsonDocumentResponse(content=envelope.model_dump(mode="json"))

    async def deliver_sse(
        self,
        request: Request,
        *,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> object:
        """交付 SSE 增量响应。"""

        if request.method == HTTP_GET_METHOD:
            identity = await self._consume_native_sse_ticket(request, binding=binding)
            command_json = request.query_params.get(SSE_COMMAND_QUERY_NAME)
            if command_json is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    error_code=CoreErrorCode.REQUEST_INVALID,
                    message="native EventSource 请求缺少 command 参数。",
                )
            command = binding.command_adapter.validate_json(command_json)
        else:
            identity = self._context_accessor.read_http(
                request,
                require_authenticated=binding.require_authenticated,
            )
            self._authorize_http(request=request, binding=binding)
            command = binding.command_adapter.validate_json(await request.body())
        if request.method == HTTP_GET_METHOD:
            self._authorize_http(request=request, binding=binding)
        now = datetime.now(UTC)
        context = StreamExecutionContext(
            request_id=identity.request_id,
            trace_id=identity.trace_id,
            subject_id=identity.subject_id,
            client_ip=identity.client_ip,
            operation_name=binding.contract.header.operation_name,
            transport=StreamTransport.SSE,
            resumable=binding.contract.detail.resumable,
            deadline=now + timedelta(seconds=binding.max_duration_seconds),
        )
        observation = self._create_observation(
            operation_name=binding.contract.header.operation_name,
            transport=StreamTransport.SSE,
            subject_id=identity.subject_id,
        )
        request.scope["state"][STREAM_ACCESS_OBSERVATION_STATE_KEY] = observation
        last_event_id = request.headers.get(LAST_EVENT_ID_HEADER)
        stream_id = request.query_params.get(STREAM_ID_QUERY_NAME)
        resume_request: SseResumeRequest | None = None
        if last_event_id is not None or stream_id is not None:
            if last_event_id is None or stream_id is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    error_code=CoreErrorCode.REQUEST_INVALID,
                    message="SSE 恢复必须同时提供 stream_id 与 Last-Event-ID。",
                )
            resume_request = SseResumeRequest(
                stream_id=stream_id,
                last_event_id=last_event_id,
            )
        if resume_request is not None:
            replay_events = await self._load_replay_events(
                request=StreamResumeRequest(
                    stream_id=resume_request.stream_id,
                    last_event_id=resume_request.last_event_id,
                    subject_id=identity.subject_id,
                    operation_name=binding.contract.header.operation_name,
                ),
                binding=binding,
            )
            events = self._iterate_replay_events(replay_events)
        else:
            live_events = self._resolve_orchestrator(binding).iter_events(
                source=binding.source,
                command=command,
                context=context,
            )
            events = self._persist_events(
                events=live_events,
                binding=binding,
                context=context,
            )
        try:
            lease = await binding.session_registry.acquire(
                identity=StreamSessionIdentity(
                    subject_id=identity.subject_id,
                    client_ip=identity.client_ip,
                    operation_name=binding.contract.header.operation_name,
                    transport=StreamTransport.SSE,
                )
            )
        except StreamSessionAdmissionError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.CAPACITY_EXHAUSTED,
                message=STREAM_SESSION_UNAVAILABLE_MESSAGE,
            ) from exc
        leased_events = self._lease_sse_events(
            events=events,
            lease=lease,
            context=context,
            observation=observation,
            binding=binding,
        )
        return self._resolve_sse_presenter(binding).create_response(leased_events)

    async def deliver_ticket(
        self,
        request: Request,
        *,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> OrjsonDocumentResponse:
        """在认证授权完成后签发短期、单次、绑定用途的访问票据。"""

        identity = self._context_accessor.read_http(
            request,
            require_authenticated=binding.require_authenticated,
        )
        self._authorize_http(request=request, binding=binding)
        if binding.ticket_service is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message="流访问票据服务尚未就绪。",
            )
        ticket = await binding.ticket_service.issue(
            subject_id=identity.subject_id,
            operation_name=binding.contract.header.operation_name,
            client_ip=identity.client_ip,
        )
        return OrjsonDocumentResponse(content=ticket.model_dump(mode="json"))

    async def _consume_native_sse_ticket(
        self,
        request: Request,
        *,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> StreamRequestIdentity:
        """原子消费 native EventSource 的短期单次票据。

        :param request: 当前 GET SSE 请求。
        :type request: Request
        :param binding: 当前流操作绑定。
        :type binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel]
        :returns: 票据绑定的流请求身份。
        :rtype: StreamRequestIdentity
        :raises HttpFaultException: 票据缺失、无效或已消费时抛出。
        """

        ticket = request.query_params.get(STREAM_TICKET_QUERY_NAME)
        subject_id = request.query_params.get(STREAM_TICKET_SUBJECT_QUERY_NAME)
        if ticket is None or subject_id is None or binding.ticket_service is None:
            raise HttpFaultException(
                status_code=HTTPStatus.FORBIDDEN,
                error_code=CoreErrorCode.STREAM_TICKET_INVALID,
                message="native EventSource 缺少有效单次票据。",
            )
        identity = self._context_accessor.read_http(request, require_authenticated=False)
        consumed = await binding.ticket_service.consume(
            ticket=ticket,
            subject_id=subject_id,
            operation_name=binding.contract.header.operation_name,
            client_ip=identity.client_ip,
        )
        if not consumed:
            raise HttpFaultException(
                status_code=HTTPStatus.FORBIDDEN,
                error_code=CoreErrorCode.STREAM_TICKET_INVALID,
                message="native EventSource 单次票据无效或已消费。",
            )
        return StreamRequestIdentity(
            request_id=identity.request_id,
            trace_id=identity.trace_id,
            subject_id=subject_id,
            client_ip=identity.client_ip,
        )

    async def deliver_websocket(
        self,
        websocket: WebSocket,
        *,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> None:
        """交付 WebSocket 双向流会话。"""

        if binding.websocket_guard is None or binding.websocket_handler is None:
            await websocket.close(code=1011)
            return
        try:
            admission = await binding.websocket_guard.authorize(
                websocket=websocket,
                operation_name=binding.contract.header.operation_name,
            )
        except PermissionError:
            await websocket.close(code=1008)
            return
        except StreamSessionAdmissionError:
            await websocket.close(code=1013)
            return
        except HttpFaultException:
            await websocket.close(code=1008)
            return
        except RuntimeError:
            await websocket.close(code=1013)
            return
        identity = self._context_accessor.read_websocket(websocket)
        observation = self._create_observation(
            operation_name=binding.contract.header.operation_name,
            transport=StreamTransport.WEBSOCKET,
            subject_id=admission.result.principal.subject_id,
        )
        websocket.scope["state"][STREAM_ACCESS_OBSERVATION_STATE_KEY] = observation
        await binding.websocket_handler.run(
            websocket=websocket,
            admission=admission,
            operation_name=binding.contract.header.operation_name,
            source=binding.source,
            request_id=identity.request_id,
            trace_id=identity.trace_id,
            observation=observation,
        )

    async def _persist_events(
        self,
        *,
        events: AsyncGenerator[StreamEventEnvelope[BaseModel], None],
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
        context: StreamExecutionContext,
    ) -> AsyncGenerator[StreamEventEnvelope[BaseModel], None]:
        """发送前把事件追加到有限重放窗口。"""

        try:
            replay_available = context.resumable
            async for event in events:
                if replay_available:
                    try:
                        await binding.state_store.append_event(
                            StreamReplayEventRecord(
                                stream_id=event.header.stream_id,
                                event_id=event.header.event_id,
                                sequence=event.header.sequence,
                                subject_id=context.subject_id,
                                operation_name=context.operation_name,
                                payload_json=binding.codec.encode(event).decode("utf-8"),
                                expires_at=datetime.now(UTC)
                                + timedelta(seconds=binding.replay_ttl_seconds),
                            ),
                            max_events=binding.replay_max_events,
                        )
                    except RuntimeError:
                        replay_available = False
                        self._logger.warning(STREAM_REPLAY_WRITE_FAILED_MESSAGE)
                yield event
        finally:
            await events.aclose()

    async def _load_replay_events(
        self,
        *,
        request: StreamResumeRequest,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> list[StreamEventEnvelope[BaseModel]]:
        """在响应启动前读取、鉴权并解码有限重放窗口。"""

        window = await binding.state_store.load_replay_window(request)
        if window.expired:
            if binding.metrics_registry is not None:
                binding.metrics_registry.record_stream_resume(
                    StreamResumeMetric(
                        transport=StreamTransport.SSE,
                        outcome=StreamMetricOutcome.REJECTED,
                    )
                )
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CoreErrorCode.STREAM_REPLAY_UNAVAILABLE,
                message=STREAM_REPLAY_INVALID_MESSAGE,
            )
        try:
            events = [binding.codec.decode(record.payload_json) for record in window.events]
        except (HttpFaultException, ValueError) as exc:
            if binding.metrics_registry is not None:
                binding.metrics_registry.record_stream_resume(
                    StreamResumeMetric(
                        transport=StreamTransport.SSE,
                        outcome=StreamMetricOutcome.REJECTED,
                    )
                )
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CoreErrorCode.STREAM_REPLAY_UNAVAILABLE,
                message=STREAM_REPLAY_INVALID_MESSAGE,
            ) from exc
        if any(event.header.stream_id != request.stream_id for event in events):
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CoreErrorCode.STREAM_REPLAY_UNAVAILABLE,
                message=STREAM_REPLAY_INVALID_MESSAGE,
            )
        if binding.metrics_registry is not None:
            binding.metrics_registry.record_stream_resume(
                StreamResumeMetric(
                    transport=StreamTransport.SSE,
                    outcome=StreamMetricOutcome.SUCCESS,
                )
            )
        return events

    async def _iterate_replay_events(
        self,
        events: list[StreamEventEnvelope[BaseModel]],
    ) -> AsyncGenerator[StreamEventEnvelope[BaseModel], None]:
        """迭代已经在响应前完成验证的重放事件。"""

        for event in events:
            yield event

    async def _lease_sse_events(
        self,
        *,
        events: AsyncGenerator[StreamEventEnvelope[BaseModel], None],
        lease: StreamSessionLease,
        context: StreamExecutionContext,
        observation: StreamAccessObservation,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> AsyncGenerator[StreamEventEnvelope[BaseModel], None]:
        """在 SSE 真实结束前持有租约并消费停机通知。"""

        current_task = asyncio.current_task()
        if current_task is not None:
            await lease.set_cancel_callback(lambda: (current_task.cancel(), None)[1])
        last_event: StreamEventEnvelope[BaseModel] | None = None
        try:
            while True:
                next_event_task = asyncio.create_task(anext(events))
                shutdown_task = asyncio.create_task(lease.shutdown_event.wait())
                done, pending = await asyncio.wait(
                    {next_event_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if shutdown_task in done and lease.shutdown_event.is_set():
                    next_event_task.cancel()
                    await asyncio.gather(next_event_task, return_exceptions=True)
                    if last_event is not None:
                        fault = StreamEventEnvelope[BaseModel](
                            header=StreamEventHeader(
                                stream_id=last_event.header.stream_id,
                                event_id=str(uuid.uuid4()),
                                sequence=last_event.header.sequence + 1,
                                event_kind="stream_fault",
                                schema_version=STREAM_SCHEMA_VERSION,
                                request_id=context.request_id,
                                trace_id=context.trace_id,
                            ),
                            detail=StreamFaultDetail(
                                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                                message=STREAM_SERVICE_SHUTDOWN_MESSAGE,
                                retryable=True,
                                close_reason=StreamCloseReason.SERVICE_SHUTDOWN,
                            ),
                        )
                        observation.event_count += 1
                        observation.close_reason = StreamCloseReason.SERVICE_SHUTDOWN
                        if binding.metrics_registry is not None:
                            binding.metrics_registry.record_stream_event(
                                StreamEventMetric(
                                    transport=StreamTransport.SSE,
                                    event_kind=StreamMetricEventKind.FAULT,
                                    byte_count=len(binding.codec.encode(fault)),
                                )
                            )
                        yield fault
                    return
                try:
                    event = next_event_task.result()
                except StopAsyncIteration:
                    return
                last_event = event
                observation.event_count += 1
                if binding.metrics_registry is not None:
                    binding.metrics_registry.record_stream_event(
                        StreamEventMetric(
                            transport=StreamTransport.SSE,
                            event_kind=StreamMetricEventKind.resolve(event.header.event_kind),
                            byte_count=len(binding.codec.encode(event)),
                        )
                    )
                if isinstance(event.detail, StreamFaultDetail):
                    observation.close_reason = event.detail.close_reason
                elif isinstance(event.detail, StreamCompletedDetail):
                    observation.close_reason = StreamCloseReason.COMPLETED
                yield event
        finally:
            await events.aclose()
            await lease.release(observation.close_reason)

    def _authorize_http(
        self,
        *,
        request: Request,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> None:
        """使用既有主体与授权守卫校验 HTTP/SSE 操作要求。"""

        requirement = binding.authorization_requirement
        if requirement is None:
            return
        principal = getattr(request.state, "authenticated_principal", None)
        if not isinstance(principal, AuthenticatedPrincipal):
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=CoreErrorCode.STREAM_TICKET_INVALID,
                message="当前流操作要求有效访问令牌。",
            )
        if binding.authorization_guard is None:
            raise RuntimeError("声明流操作授权要求时必须提供既有授权守卫。")
        binding.authorization_guard.assert_requirement(
            principal=principal,
            requirement=requirement,
        )

    def _create_observation(
        self,
        *,
        operation_name: str,
        transport: StreamTransport,
        subject_id: str,
    ) -> StreamAccessObservation:
        """构建仅包含主体摘要的流访问观测状态。"""

        return StreamAccessObservation(
            operation_name=operation_name,
            transport=transport,
            subject_digest=sha256(subject_id.encode(STREAM_SUBJECT_DIGEST_ENCODING)).hexdigest(),
        )

    def _resolve_orchestrator(
        self,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> StreamExecutionOrchestrator[BaseModel, BaseModel]:
        """让新连接读取当前热更新后的发送超时。"""

        if binding.runtime_provider is None:
            return binding.orchestrator
        detail = binding.runtime_provider().detail
        return StreamExecutionOrchestrator(
            event_adapter=binding.event_adapter,
            policy=StreamExecutionPolicy(
                queue_capacity=detail.queue_capacity,
                send_timeout_seconds=detail.send_timeout_seconds,
                max_duration_seconds=detail.max_duration_seconds,
                max_event_bytes=detail.max_event_bytes,
            ),
            queue_saturation_observer=binding.queue_saturation_observer,
        )

    def _resolve_sse_presenter(
        self,
        binding: StreamOperationBinding[BaseModel, BaseModel, BaseModel],
    ) -> SseResponsePresenter[BaseModel]:
        """让新 SSE 连接读取当前热更新后的心跳、重试与发送超时。"""

        if binding.runtime_provider is None:
            return binding.sse_presenter
        detail = binding.runtime_provider().detail
        return SseResponsePresenter(
            codec=binding.codec,
            heartbeat_seconds=detail.sse_heartbeat_seconds,
            retry_milliseconds=detail.sse_retry_milliseconds,
            send_timeout_seconds=detail.send_timeout_seconds,
        )

    def _validate_bindings(
        self,
        *,
        app: FastAPI,
        bindings: list[StreamOperationBinding[BaseModel, BaseModel, BaseModel]],
    ) -> None:
        """校验操作名、路径和事件绑定唯一。"""

        operation_names: set[str] = {
            operation_id
            for route in app.routes
            if isinstance((operation_id := getattr(route, "operation_id", None)), str)
        }
        paths: set[str] = {
            path for route in app.routes if isinstance((path := getattr(route, "path", None)), str)
        }
        for binding in bindings:
            operation_name = binding.contract.header.operation_name
            generated_operation_ids = {
                f"{operation_name}_batch",
                f"{operation_name}_sse_post",
                f"{operation_name}_sse_get",
                f"{operation_name}_ticket",
            }
            if operation_name in operation_names or operation_names.intersection(
                generated_operation_ids
            ):
                raise ValueError("流操作 operation_name 必须唯一。")
            operation_names.update(generated_operation_ids)
            detail = binding.contract.detail
            for path in (
                detail.batch_path,
                detail.sse_path,
                detail.websocket_path,
                detail.ticket_path,
            ):
                if path is None:
                    continue
                if path in paths:
                    raise ValueError("流操作交付路径必须唯一。")
                paths.add(path)
