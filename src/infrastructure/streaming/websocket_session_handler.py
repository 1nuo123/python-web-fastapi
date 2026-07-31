"""WebSocket 流会话收发与控制编排。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Generic, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from src.application.ports.stream_event_source_port import (
    StreamEventSourcePort,
    StreamExecutionContext,
)
from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.application.streaming.stream_execution_orchestrator import StreamExecutionOrchestrator
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.stream_contract.stream_access_contract import (
    StreamReplayEventRecord,
    StreamResumeRequest,
)
from src.core.stream_contract.stream_control_contract import (
    CancelControlDetail,
    PingControlDetail,
    ResumeControlDetail,
    StreamClientControlEnvelope,
    SubscribeControlDetail,
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
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec
from src.infrastructure.streaming.stream_observation import StreamAccessObservation
from src.infrastructure.streaming.websocket_connection_guard import (
    WEBSOCKET_CLOSE_CODE_BY_REASON,
    AuthorizedWebSocketAdmission,
    WebSocketCloseCode,
)

WEBSOCKET_CANCELLED_MESSAGE = "客户端已取消流操作。"
WEBSOCKET_CONTROL_INVALID_MESSAGE = "WebSocket 控制帧不符合契约。"
WEBSOCKET_CREDENTIAL_EXPIRED_MESSAGE = "WebSocket 凭证已过期。"
WEBSOCKET_PONG_EVENT_NAME: Literal["pong"] = "pong"
WEBSOCKET_REPLAY_WRITE_FAILED_MESSAGE = (
    "WebSocket 恢复窗口写入失败，当前实时发送继续且恢复能力已关闭。"
)
WEBSOCKET_SERVICE_SHUTDOWN_MESSAGE = "服务正在停机，WebSocket 流会话即将关闭。"
WEBSOCKET_SLOW_CONSUMER_MESSAGE = "WebSocket 客户端消费速度过慢。"

T_StreamCommand = TypeVar("T_StreamCommand", bound=BaseModel)
T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)
T_StreamControl = TypeVar("T_StreamControl", bound=BaseModel)


class WebSocketMessageTooLargeError(ValueError):
    """WebSocket 控制帧超过最大字节限制。"""


class WebSocketSlowConsumerError(TimeoutError):
    """WebSocket 客户端消费速度超过发送超时。"""


class WebSocketPongPayload(BaseModel):
    """WebSocket 探活响应。"""

    model_config = ConfigDict(extra="forbid")

    event: Literal["pong"] = WEBSOCKET_PONG_EVENT_NAME
    nonce: str


@dataclass(slots=True)
class WebSocketTerminationState:
    """WebSocket 并发收发共享的终止状态。"""

    event: asyncio.Event
    reason: StreamCloseReason | None = None
    last_event: StreamEventEnvelope[BaseModel] | None = None
    terminal_fault_sent: bool = False


@dataclass(frozen=True, slots=True)
class WebSocketSubscribeStart(Generic[T_StreamCommand]):
    """首次订阅启动状态。"""

    command: T_StreamCommand


@dataclass(frozen=True, slots=True)
class WebSocketResumeStart:
    """新连接首次恢复启动状态。"""

    request: ResumeControlDetail


class WebSocketSessionHandler(Generic[T_StreamCommand, T_StreamDetail, T_StreamControl]):
    """并发执行 WebSocket 事件发送与控制接收。"""

    def __init__(
        self,
        *,
        command_adapter: TypeAdapter[T_StreamCommand],
        control_adapter: TypeAdapter[StreamClientControlEnvelope[T_StreamControl]],
        orchestrator: StreamExecutionOrchestrator[T_StreamCommand, T_StreamDetail],
        codec: StreamEventCodec[T_StreamDetail],
        state_store: StreamStateStorePort,
        max_message_bytes: int,
        send_timeout_seconds: float,
        replay_ttl_seconds: int,
        replay_max_events: int,
        max_duration_seconds: float,
        metrics_registry: PrometheusMetricsRegistry | None = None,
        runtime_provider: Callable[[], StreamRuntimeEnvelope] | None = None,
    ) -> None:
        """初始化 WebSocket 会话处理器。"""

        self._command_adapter = command_adapter
        self._control_adapter = control_adapter
        self._orchestrator = orchestrator
        self._codec = codec
        self._state_store = state_store
        self._max_message_bytes = max_message_bytes
        self._send_timeout_seconds = send_timeout_seconds
        self._replay_ttl_seconds = replay_ttl_seconds
        self._replay_max_events = replay_max_events
        self._max_duration_seconds = max_duration_seconds
        self._metrics_registry = metrics_registry
        self._runtime_provider = runtime_provider
        self._logger = logging.getLogger(__name__)

    async def run(
        self,
        *,
        websocket: WebSocket,
        admission: AuthorizedWebSocketAdmission,
        operation_name: str,
        source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail],
        request_id: str,
        trace_id: str | None,
        observation: StreamAccessObservation,
    ) -> None:
        """运行单个 WebSocket 流会话。

        :param websocket: 已准入但尚未接受的连接。
        :type websocket: WebSocket
        :param admission: 准入结果与会话租约。
        :type admission: AuthorizedWebSocketAdmission
        :param operation_name: 流操作名。
        :type operation_name: str
        :param source: 业务事件源。
        :type source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail]
        :param request_id: 连接请求标识。
        :type request_id: str
        :param trace_id: 链路标识。
        :type trace_id: str | None
        """

        await websocket.accept(subprotocol=admission.result.subprotocol)
        termination = WebSocketTerminationState(event=asyncio.Event())
        send_lock = asyncio.Lock()
        current_task = asyncio.current_task()
        if current_task is not None:
            await admission.lease.set_cancel_callback(lambda: (current_task.cancel(), None)[1])
        credential_deadline = admission.result.credential_expires_at
        runtime_deadline = datetime.now(UTC) + timedelta(
            seconds=self._current_max_duration_seconds()
        )
        deadline = (
            min(runtime_deadline, credential_deadline)
            if credential_deadline is not None
            else runtime_deadline
        )
        context = StreamExecutionContext(
            request_id=request_id,
            trace_id=trace_id,
            subject_id=admission.result.principal.subject_id,
            client_ip=admission.result.client_ip,
            operation_name=operation_name,
            transport=StreamTransport.WEBSOCKET,
            resumable=True,
            deadline=deadline,
        )
        try:
            start = await self._receive_start(websocket)
            if isinstance(start, WebSocketResumeStart):
                await self._send_replay_start(
                    websocket=websocket,
                    admission=admission,
                    operation_name=operation_name,
                    resume=start.request,
                    send_lock=send_lock,
                    observation=observation,
                )
                await self._close_websocket(websocket, WebSocketCloseCode.NORMAL)
                return
            command = start.command
            async with asyncio.TaskGroup() as task_group:
                sender = task_group.create_task(
                    self._capture_session_task(
                        self._send_events(
                            websocket=websocket,
                            source=source,
                            command=command,
                            context=context,
                            termination=termination,
                            send_lock=send_lock,
                            observation=observation,
                        )
                    )
                )
                receiver = task_group.create_task(
                    self._capture_session_task(
                        self._receive_controls(
                            websocket=websocket,
                            termination=termination,
                            send_lock=send_lock,
                        )
                    )
                )
                deadline_task = task_group.create_task(
                    self._capture_session_task(
                        self._wait_credential_deadline(
                            admission=admission,
                            termination=termination,
                        )
                    )
                )
                shutdown = task_group.create_task(
                    self._capture_session_task(
                        self._wait_service_shutdown(
                            admission=admission,
                            termination=termination,
                        )
                    )
                )
                session_tasks = (sender, receiver, deadline_task, shutdown)
                _, pending = await asyncio.wait(
                    session_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if termination.event.is_set() and sender in pending:
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(sender),
                            timeout=self._current_send_timeout_seconds() * 2,
                        )
                    except TimeoutError:
                        sender.cancel()
                for task in session_tasks:
                    if not task.done():
                        task.cancel()
            task_results = tuple(task.result() for task in session_tasks if not task.cancelled())
            completed_exceptions = [
                result for result in task_results if isinstance(result, Exception)
            ]
            unexpected_exception = next(
                (
                    exception
                    for exception in completed_exceptions
                    if not isinstance(exception, WebSocketDisconnect)
                ),
                None,
            )
            if unexpected_exception is not None:
                raise unexpected_exception
            if any(
                isinstance(exception, WebSocketDisconnect) for exception in completed_exceptions
            ):
                return
            await self._close_websocket(
                websocket,
                self._map_close_code(termination.reason),
            )
        except WebSocketDisconnect:
            return
        except WebSocketMessageTooLargeError:
            await self._close_websocket(websocket, WebSocketCloseCode.MESSAGE_TOO_LARGE)
        except WebSocketSlowConsumerError:
            await self._send_terminal_fault(
                websocket=websocket,
                context=context,
                termination=termination,
                error_code=CoreErrorCode.STREAM_SLOW_CONSUMER,
                message=WEBSOCKET_SLOW_CONSUMER_MESSAGE,
                close_reason=StreamCloseReason.SLOW_CONSUMER,
                retryable=True,
                send_lock=send_lock,
            )
            await self._close_websocket(websocket, WebSocketCloseCode.OVERLOADED)
        except (PermissionError, ValidationError, ValueError):
            await self._send_terminal_fault(
                websocket=websocket,
                context=context,
                termination=termination,
                error_code=CoreErrorCode.STREAM_PROTOCOL_INVALID,
                message=WEBSOCKET_CONTROL_INVALID_MESSAGE,
                close_reason=StreamCloseReason.POLICY_REJECTED,
                retryable=False,
                send_lock=send_lock,
            )
            await self._close_websocket(websocket, WebSocketCloseCode.POLICY_REJECTED)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._close_websocket(websocket, WebSocketCloseCode.INTERNAL_ERROR)
        finally:
            await admission.lease.release(termination.reason or observation.close_reason)

    async def _capture_session_task(
        self,
        awaitable: Awaitable[None],
    ) -> Exception | None:
        """把并发循环异常转换为 TaskGroup 可统一检查的结果。"""

        try:
            await awaitable
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return exc
        return None

    async def _receive_start(
        self,
        websocket: WebSocket,
    ) -> WebSocketSubscribeStart[T_StreamCommand] | WebSocketResumeStart:
        """读取并校验新订阅或新连接恢复控制帧。"""

        payload = await self._receive_text(websocket)
        self._validate_message_size(payload)
        control = self._control_adapter.validate_json(payload)
        if isinstance(control.detail, SubscribeControlDetail):
            return WebSocketSubscribeStart(
                command=self._command_adapter.validate_python(control.detail.command)
            )
        if isinstance(control.detail, ResumeControlDetail):
            return WebSocketResumeStart(request=control.detail)
        raise ValueError(WEBSOCKET_CONTROL_INVALID_MESSAGE)

    async def _send_replay_start(
        self,
        *,
        websocket: WebSocket,
        admission: AuthorizedWebSocketAdmission,
        operation_name: str,
        resume: ResumeControlDetail,
        send_lock: asyncio.Lock,
        observation: StreamAccessObservation,
    ) -> None:
        """在新连接内发送已鉴权且保持原序号的有限重放事件。"""

        window = await self._state_store.load_replay_window(
            StreamResumeRequest(
                stream_id=resume.stream_id,
                last_event_id=resume.last_event_id,
                subject_id=admission.result.principal.subject_id,
                operation_name=operation_name,
            )
        )
        if window.expired:
            if self._metrics_registry is not None:
                self._metrics_registry.record_stream_resume(
                    StreamResumeMetric(
                        transport=StreamTransport.WEBSOCKET,
                        outcome=StreamMetricOutcome.REJECTED,
                    )
                )
            raise PermissionError("恢复窗口已过期或不属于当前主体。")
        for record in window.events:
            event = self._codec.decode(record.payload_json)
            await self._send_event(websocket, event, send_lock)
            observation.event_count += 1
            if isinstance(event.detail, StreamFaultDetail):
                observation.close_reason = event.detail.close_reason
            elif isinstance(event.detail, StreamCompletedDetail):
                observation.close_reason = StreamCloseReason.COMPLETED
            self._record_event_metric(event)
        if observation.close_reason is StreamCloseReason.INTERNAL_ERROR:
            observation.close_reason = StreamCloseReason.COMPLETED
        if self._metrics_registry is not None:
            self._metrics_registry.record_stream_resume(
                StreamResumeMetric(
                    transport=StreamTransport.WEBSOCKET,
                    outcome=StreamMetricOutcome.SUCCESS,
                )
            )

    async def _send_events(
        self,
        *,
        websocket: WebSocket,
        source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail],
        command: T_StreamCommand,
        context: StreamExecutionContext,
        termination: WebSocketTerminationState,
        send_lock: asyncio.Lock,
        observation: StreamAccessObservation,
    ) -> None:
        """发送统一事件并响应客户端取消。"""

        events: AsyncGenerator[StreamEventEnvelope[T_StreamDetail], None] = (
            self._orchestrator.iter_events(
                source=source,
                command=command,
                context=context,
            )
        )
        last_event: StreamEventEnvelope[T_StreamDetail] | None = None
        replay_available = context.resumable
        try:
            while True:
                next_event_task: asyncio.Task[StreamEventEnvelope[T_StreamDetail]] = (
                    asyncio.ensure_future(anext(events))
                )
                cancel_task = asyncio.create_task(termination.event.wait())
                try:
                    done, pending = await asyncio.wait(
                        {next_event_task, cancel_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    next_event_task.cancel()
                    cancel_task.cancel()
                    await asyncio.gather(
                        next_event_task,
                        cancel_task,
                        return_exceptions=True,
                    )
                    raise
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if cancel_task in done and termination.event.is_set():
                    next_event_task.cancel()
                    await asyncio.gather(next_event_task, return_exceptions=True)
                    if last_event is None:
                        return
                    reason = termination.reason or StreamCloseReason.CLIENT_CANCELLED
                    fault_message = (
                        WEBSOCKET_SERVICE_SHUTDOWN_MESSAGE
                        if reason is StreamCloseReason.SERVICE_SHUTDOWN
                        else WEBSOCKET_CREDENTIAL_EXPIRED_MESSAGE
                        if reason is StreamCloseReason.POLICY_REJECTED
                        else WEBSOCKET_CANCELLED_MESSAGE
                    )
                    fault = self._build_fault_event(
                        context=context,
                        last_event=last_event,
                        error_code=(
                            CoreErrorCode.RESOURCE_NOT_READY
                            if reason is StreamCloseReason.SERVICE_SHUTDOWN
                            else CoreErrorCode.STREAM_PROTOCOL_INVALID
                        ),
                        message=fault_message,
                        close_reason=reason,
                        retryable=reason is StreamCloseReason.SERVICE_SHUTDOWN,
                    )
                    await self._send_event(websocket, fault, send_lock)
                    termination.terminal_fault_sent = True
                    observation.event_count += 1
                    observation.close_reason = reason
                    self._record_event_metric(fault)
                    return
                try:
                    event = next_event_task.result()
                except StopAsyncIteration:
                    break
                await self._send_event(websocket, event, send_lock)
                observation.event_count += 1
                self._record_event_metric(event)
                if isinstance(event.detail, StreamFaultDetail):
                    observation.close_reason = event.detail.close_reason
                elif isinstance(event.detail, StreamCompletedDetail):
                    observation.close_reason = StreamCloseReason.COMPLETED
                if replay_available:
                    try:
                        await self._state_store.append_event(
                            StreamReplayEventRecord(
                                stream_id=event.header.stream_id,
                                event_id=event.header.event_id,
                                sequence=event.header.sequence,
                                subject_id=context.subject_id,
                                operation_name=context.operation_name,
                                payload_json=self._codec.encode(event).decode("utf-8"),
                                expires_at=datetime.now(UTC)
                                + timedelta(seconds=self._replay_ttl_seconds),
                            ),
                            max_events=self._replay_max_events,
                        )
                    except RuntimeError:
                        replay_available = False
                        self._logger.warning(WEBSOCKET_REPLAY_WRITE_FAILED_MESSAGE)
                last_event = event
                termination.last_event = cast(StreamEventEnvelope[BaseModel], event)
        finally:
            await events.aclose()
        if last_event is None:
            raise RuntimeError("WebSocket 流未产生任何事件。")

    async def _receive_controls(
        self,
        *,
        websocket: WebSocket,
        termination: WebSocketTerminationState,
        send_lock: asyncio.Lock,
    ) -> None:
        """接收取消、恢复和探活控制帧。"""

        try:
            while not termination.event.is_set():
                payload = await self._receive_text(websocket)
                self._validate_message_size(payload)
                control = self._control_adapter.validate_json(payload)
                if isinstance(control.detail, CancelControlDetail):
                    termination.reason = StreamCloseReason.CLIENT_CANCELLED
                    termination.event.set()
                    return
                if isinstance(control.detail, PingControlDetail):
                    async with send_lock:
                        await websocket.send_text(
                            WebSocketPongPayload(nonce=control.detail.nonce).model_dump_json()
                        )
                    continue
                if isinstance(control.detail, ResumeControlDetail):
                    termination.reason = StreamCloseReason.POLICY_REJECTED
                    termination.event.set()
                    raise ValueError("运行中的 WebSocket 流不得切换恢复窗口。")
                termination.reason = StreamCloseReason.POLICY_REJECTED
                termination.event.set()
                raise ValueError(WEBSOCKET_CONTROL_INVALID_MESSAGE)
        except WebSocketDisconnect:
            termination.reason = StreamCloseReason.CLIENT_DISCONNECTED
            termination.event.set()
        except (ValidationError, ValueError):
            termination.reason = StreamCloseReason.POLICY_REJECTED
            termination.event.set()
            raise

    async def _wait_credential_deadline(
        self,
        *,
        admission: AuthorizedWebSocketAdmission,
        termination: WebSocketTerminationState,
    ) -> None:
        """在凭证硬截止时间触发连接终止。"""

        expires_at = admission.result.principal.credential_expires_at
        if expires_at is None:
            await termination.event.wait()
            return
        delay = max(0.0, (expires_at - datetime.now(UTC)).total_seconds())
        await asyncio.sleep(delay)
        termination.reason = StreamCloseReason.POLICY_REJECTED
        termination.event.set()

    async def _wait_service_shutdown(
        self,
        *,
        admission: AuthorizedWebSocketAdmission,
        termination: WebSocketTerminationState,
    ) -> None:
        """消费共享租约的服务停机通知。"""

        await admission.lease.shutdown_event.wait()
        termination.reason = StreamCloseReason.SERVICE_SHUTDOWN
        termination.event.set()

    async def _send_terminal_fault(
        self,
        *,
        websocket: WebSocket,
        context: StreamExecutionContext,
        termination: WebSocketTerminationState,
        error_code: CoreErrorCode,
        message: str,
        close_reason: StreamCloseReason,
        retryable: bool,
        send_lock: asyncio.Lock,
    ) -> None:
        """在关闭前尽力发送一次强类型流故障事件。"""

        if termination.terminal_fault_sent:
            return
        fault = self._build_fault_event(
            context=context,
            last_event=termination.last_event,
            error_code=error_code,
            message=message,
            close_reason=close_reason,
            retryable=retryable,
        )
        try:
            await self._send_event(websocket, fault, send_lock)
        except (WebSocketDisconnect, WebSocketSlowConsumerError, RuntimeError):
            return
        termination.terminal_fault_sent = True

    def _build_fault_event(
        self,
        *,
        context: StreamExecutionContext,
        last_event: StreamEventEnvelope[BaseModel] | StreamEventEnvelope[T_StreamDetail] | None,
        error_code: CoreErrorCode,
        message: str,
        close_reason: StreamCloseReason,
        retryable: bool,
    ) -> StreamEventEnvelope[T_StreamDetail]:
        """基于当前会话末事件构建连续的故障终止事件。"""

        return StreamEventEnvelope[T_StreamDetail](
            header=StreamEventHeader(
                stream_id=(
                    last_event.header.stream_id if last_event is not None else str(uuid.uuid4())
                ),
                event_id=str(uuid.uuid4()),
                sequence=(last_event.header.sequence + 1 if last_event is not None else 0),
                event_kind="stream_fault",
                schema_version=STREAM_SCHEMA_VERSION,
                request_id=context.request_id,
                trace_id=context.trace_id,
            ),
            detail=cast(
                T_StreamDetail,
                StreamFaultDetail(
                    error_code=error_code,
                    message=message,
                    retryable=retryable,
                    close_reason=close_reason,
                ),
            ),
        )

    def _map_close_code(self, reason: StreamCloseReason | None) -> WebSocketCloseCode:
        """把统一终止原因映射为稳定 WebSocket 关闭码。"""

        if reason is None:
            return WebSocketCloseCode.NORMAL
        return WEBSOCKET_CLOSE_CODE_BY_REASON.get(reason, WebSocketCloseCode.NORMAL)

    def _record_event_metric(self, event: StreamEventEnvelope[T_StreamDetail]) -> None:
        """记录受控类型与字节数，不使用 stream_id 标签。"""

        if self._metrics_registry is None:
            return
        self._metrics_registry.record_stream_event(
            StreamEventMetric(
                transport=StreamTransport.WEBSOCKET,
                event_kind=StreamMetricEventKind.resolve(event.header.event_kind),
                byte_count=len(self._codec.encode(event)),
            )
        )

    async def _send_event(
        self,
        websocket: WebSocket,
        event: StreamEventEnvelope[T_StreamDetail],
        send_lock: asyncio.Lock,
    ) -> None:
        """按发送超时写入单个事件。"""

        payload = self._codec.encode(event).decode("utf-8")
        async with send_lock:
            try:
                await asyncio.wait_for(
                    websocket.send_text(payload),
                    timeout=self._current_send_timeout_seconds(),
                )
            except TimeoutError as exc:
                raise WebSocketSlowConsumerError("WebSocket 发送超时。") from exc

    def _validate_message_size(self, payload: str) -> None:
        """校验客户端文本帧字节上限。"""

        if len(payload.encode("utf-8")) > self._current_max_message_bytes():
            raise WebSocketMessageTooLargeError("WebSocket 控制帧超过最大字节限制。")

    def _current_send_timeout_seconds(self) -> float:
        """读取当前连接可用的发送超时热配置。"""

        if self._runtime_provider is None:
            return self._send_timeout_seconds
        return self._runtime_provider().detail.send_timeout_seconds

    def _current_max_message_bytes(self) -> int:
        """读取 WebSocket 消息上限重启配置。"""

        if self._runtime_provider is None:
            return self._max_message_bytes
        return self._runtime_provider().detail.websocket_max_message_bytes

    def _current_max_duration_seconds(self) -> float:
        """读取 WebSocket 会话持续时间重启配置。"""

        if self._runtime_provider is None:
            return self._max_duration_seconds
        return self._runtime_provider().detail.max_duration_seconds

    async def _receive_text(self, websocket: WebSocket) -> str:
        """只接收 UTF-8 JSON 文本帧。"""

        try:
            return await websocket.receive_text()
        except (KeyError, RuntimeError) as exc:
            raise ValueError("WebSocket 仅允许 UTF-8 JSON 文本帧。") from exc

    async def _close_websocket(self, websocket: WebSocket, code: int) -> None:
        """在连接仍可写时关闭 WebSocket。

        :param websocket: 当前 WebSocket 连接。
        :type websocket: WebSocket
        :param code: 标准关闭码。
        :type code: int
        :returns: 无返回值。
        :rtype: None
        """

        if (
            websocket.application_state is WebSocketState.CONNECTED
            and websocket.client_state is WebSocketState.CONNECTED
        ):
            await websocket.close(code=code)
