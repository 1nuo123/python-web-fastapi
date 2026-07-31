"""协议无关的流执行与聚合编排器。"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from time import perf_counter
from typing import Generic, Protocol, TypeVar, cast

from opentelemetry import trace
from pydantic import BaseModel, TypeAdapter
from pydantic_core import ValidationError

from src.application.ports.stream_event_source_port import (
    StreamEventSourcePort,
    StreamExecutionContext,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.stream_contract.stream_delivery_contract import (
    StreamBatchCompletedDetail,
    StreamBatchEnvelope,
    StreamBatchHeader,
    StreamBatchRejectedDetail,
    StreamBatchResultKind,
    StreamCollectionLimit,
)
from src.core.stream_contract.stream_event_contract import (
    STREAM_SCHEMA_VERSION,
    StreamCloseReason,
    StreamCompletedDetail,
    StreamEventEnvelope,
    StreamEventHeader,
    StreamFaultDetail,
    StreamStartedDetail,
    StreamTransport,
)

STREAM_EVENT_TEXT_ENCODING = "utf-8"
STREAM_COLLECTION_LIMIT_MESSAGE = "非流式聚合超过已配置上限。"
STREAM_EXECUTION_TIMEOUT_MESSAGE = "流执行超过最大持续时间。"
STREAM_PRODUCER_FAILED_MESSAGE = "流事件生产失败。"
STREAM_SLOW_CONSUMER_MESSAGE = "流消费者处理速度过慢。"
STREAM_EVENT_INVALID_MESSAGE = "流事件不符合已冻结契约。"
STREAM_EVENT_SIZE_LIMIT_MESSAGE = "流事件超过最大字节限制。"

T_StreamCommand = TypeVar("T_StreamCommand", bound=BaseModel)
T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)


class StreamQueueSaturationObserverPort(Protocol):
    """应用编排器使用的队列饱和度观测端口。"""

    def record(self, *, transport: StreamTransport, ratio: float) -> None:
        """记录低基数队列饱和度。"""

        ...


@dataclass(frozen=True, slots=True)
class StreamExecutionPolicy:
    """流执行限制策略。"""

    queue_capacity: int
    send_timeout_seconds: float
    max_duration_seconds: float
    max_event_bytes: int


@dataclass(frozen=True, slots=True)
class StreamProducerTerminal:
    """生产者内部终态。"""

    exception: Exception | None


class StreamExecutionOrchestrator(Generic[T_StreamCommand, T_StreamDetail]):
    """统一流事件执行与聚合编排器。"""

    def __init__(
        self,
        *,
        event_adapter: TypeAdapter[StreamEventEnvelope[T_StreamDetail]],
        policy: StreamExecutionPolicy,
        queue_saturation_observer: StreamQueueSaturationObserverPort | None = None,
    ) -> None:
        """初始化执行编排器。

        :param event_adapter: 业务事件信封强类型适配器。
        :type event_adapter: TypeAdapter[StreamEventEnvelope[T_StreamDetail]]
        :param policy: 流执行限制策略。
        :type policy: StreamExecutionPolicy
        """

        self._event_adapter = event_adapter
        self._policy = policy
        self._queue_saturation_observer = queue_saturation_observer

    async def iter_events(
        self,
        *,
        source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail],
        command: T_StreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncGenerator[StreamEventEnvelope[T_StreamDetail], None]:
        """迭代规范化流事件。

        :param source: 业务事件源。
        :type source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail]
        :param command: 强类型业务命令。
        :type command: T_StreamCommand
        :param context: 流执行上下文。
        :type context: StreamExecutionContext
        :returns: 规范化事件异步迭代器。
        :rtype: AsyncIterator[StreamEventEnvelope[T_StreamDetail]]
        """

        stream_id = str(uuid.uuid4())
        span = trace.get_tracer(__name__).start_span(
            "stream.session",
            attributes={
                "stream.operation": context.operation_name,
                "stream.transport": context.transport.value,
            },
        )
        sequence = 0
        event_count = 0
        queue: asyncio.Queue[T_StreamDetail | StreamProducerTerminal] = asyncio.Queue(
            maxsize=self._policy.queue_capacity
        )
        producer = asyncio.create_task(
            self._produce(source=source, command=command, context=context, queue=queue)
        )
        try:
            started = self._build_event(
                stream_id=stream_id,
                sequence=sequence,
                context=context,
                detail=StreamStartedDetail(
                    operation_name=context.operation_name,
                    transport=context.transport,
                    resumable=context.resumable,
                ),
            )
            yield self._validate_event(started)
            sequence += 1
            event_count += 1
            remaining_seconds = max(
                0.0,
                (context.deadline - datetime.now(UTC)).total_seconds(),
            )
            execution_timeout_seconds = min(
                self._policy.max_duration_seconds,
                remaining_seconds,
            )
            async with asyncio.timeout(execution_timeout_seconds):
                while True:
                    queue_item = await queue.get()
                    if isinstance(queue_item, StreamProducerTerminal):
                        if queue_item.exception is not None:
                            span.record_exception(queue_item.exception)
                            slow_consumer = isinstance(queue_item.exception, TimeoutError)
                            fault = self._build_fault_event(
                                stream_id=stream_id,
                                sequence=sequence,
                                context=context,
                                error_code=(
                                    CoreErrorCode.STREAM_SLOW_CONSUMER
                                    if slow_consumer
                                    else CoreErrorCode.INTERNAL_UNEXPECTED
                                ),
                                message=(
                                    STREAM_SLOW_CONSUMER_MESSAGE
                                    if slow_consumer
                                    else STREAM_PRODUCER_FAILED_MESSAGE
                                ),
                                retryable=slow_consumer,
                                close_reason=(
                                    StreamCloseReason.SLOW_CONSUMER
                                    if slow_consumer
                                    else StreamCloseReason.INTERNAL_ERROR
                                ),
                            )
                            yield self._validate_event(fault)
                        else:
                            completed = self._build_event(
                                stream_id=stream_id,
                                sequence=sequence,
                                context=context,
                                detail=StreamCompletedDetail(
                                    last_sequence=sequence,
                                    event_count=event_count + 1,
                                ),
                            )
                            yield self._validate_event(completed)
                        break
                    try:
                        event = self._build_event(
                            stream_id=stream_id,
                            sequence=sequence,
                            context=context,
                            detail=queue_item,
                        )
                        yield self._validate_event(event)
                        sequence += 1
                        event_count += 1
                    except (ValidationError, HttpFaultException, AttributeError, ValueError) as exc:
                        span.record_exception(exc)
                        event_too_large = (
                            isinstance(exc, HttpFaultException)
                            and exc.error_code == CoreErrorCode.REQUEST_PAYLOAD_TOO_LARGE
                        )
                        yield self._validate_event(
                            self._build_fault_event(
                                stream_id=stream_id,
                                sequence=sequence,
                                context=context,
                                error_code=(
                                    CoreErrorCode.REQUEST_PAYLOAD_TOO_LARGE
                                    if event_too_large
                                    else CoreErrorCode.STREAM_PROTOCOL_INVALID
                                ),
                                message=(
                                    STREAM_EVENT_SIZE_LIMIT_MESSAGE
                                    if event_too_large
                                    else STREAM_EVENT_INVALID_MESSAGE
                                ),
                                retryable=False,
                                close_reason=StreamCloseReason.POLICY_REJECTED,
                            )
                        )
                        break
        except TimeoutError:
            fault = self._build_fault_event(
                stream_id=stream_id,
                sequence=sequence,
                context=context,
                error_code=CoreErrorCode.REQUEST_TIMEOUT,
                message=STREAM_EXECUTION_TIMEOUT_MESSAGE,
                retryable=True,
                close_reason=StreamCloseReason.TIMEOUT,
            )
            yield self._validate_event(fault)
        except asyncio.CancelledError:
            raise
        finally:
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass
            span.end()

    async def collect(
        self,
        *,
        source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail],
        command: T_StreamCommand,
        context: StreamExecutionContext,
        limit: StreamCollectionLimit,
    ) -> StreamBatchEnvelope[T_StreamDetail]:
        """聚合同一事件源为有界非流式结果。

        :param source: 业务事件源。
        :type source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail]
        :param command: 强类型业务命令。
        :type command: T_StreamCommand
        :param context: 流执行上下文。
        :type context: StreamExecutionContext
        :param limit: 聚合三重限制。
        :type limit: StreamCollectionLimit
        :returns: 有界聚合结果。
        :rtype: StreamBatchEnvelope[T_StreamDetail]
        :raises HttpFaultException: 命中事件数、字节数或时间上限时抛出。
        """

        events: list[StreamEventEnvelope[T_StreamDetail]] = []
        total_bytes = 0
        started_at = perf_counter()
        event_iterator = self.iter_events(
            source=source,
            command=command,
            context=context,
        )
        try:
            async with asyncio.timeout(limit.timeout_seconds):
                async for event in event_iterator:
                    event_bytes = len(event.model_dump_json().encode(STREAM_EVENT_TEXT_ENCODING))
                    if (
                        len(events) + 1 > limit.max_events
                        or total_bytes + event_bytes > limit.max_bytes
                    ):
                        raise HttpFaultException(
                            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            error_code=CoreErrorCode.CAPACITY_EXHAUSTED,
                            message=STREAM_COLLECTION_LIMIT_MESSAGE,
                        )
                    events.append(event)
                    total_bytes += event_bytes
                    if perf_counter() - started_at > limit.timeout_seconds:
                        raise HttpFaultException(
                            status_code=HTTPStatus.REQUEST_TIMEOUT,
                            error_code=CoreErrorCode.REQUEST_TIMEOUT,
                            message=STREAM_COLLECTION_LIMIT_MESSAGE,
                        )
        except TimeoutError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.REQUEST_TIMEOUT,
                error_code=CoreErrorCode.REQUEST_TIMEOUT,
                message=STREAM_COLLECTION_LIMIT_MESSAGE,
            ) from exc
        finally:
            await event_iterator.aclose()
        if not events:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.INTERNAL_UNEXPECTED,
                message=STREAM_PRODUCER_FAILED_MESSAGE,
            )
        terminal_event = events[-1]
        stream_id = events[0].header.stream_id
        if isinstance(terminal_event.detail, StreamFaultDetail):
            return StreamBatchEnvelope[T_StreamDetail](
                header=StreamBatchHeader(
                    stream_id=stream_id,
                    result_kind=StreamBatchResultKind.REJECTED,
                ),
                detail=StreamBatchRejectedDetail(
                    error_code=terminal_event.detail.error_code,
                    message=terminal_event.detail.message,
                    retryable=terminal_event.detail.retryable,
                    close_reason=terminal_event.detail.close_reason,
                    last_sequence=terminal_event.header.sequence,
                    event_count=len(events),
                    total_bytes=total_bytes,
                    terminal_event_id=terminal_event.header.event_id,
                ),
            )
        return StreamBatchEnvelope[T_StreamDetail](
            header=StreamBatchHeader(
                stream_id=stream_id,
                result_kind=StreamBatchResultKind.COMPLETED,
            ),
            detail=StreamBatchCompletedDetail[T_StreamDetail](
                events=events,
                last_sequence=terminal_event.header.sequence,
                event_count=len(events),
                total_bytes=total_bytes,
                terminal_event_id=terminal_event.header.event_id,
            ),
        )

    async def _produce(
        self,
        *,
        source: StreamEventSourcePort[T_StreamCommand, T_StreamDetail],
        command: T_StreamCommand,
        context: StreamExecutionContext,
        queue: asyncio.Queue[T_StreamDetail | StreamProducerTerminal],
    ) -> None:
        """生产业务事件并写入有界队列。"""

        iterator = source.open(command=command, context=context)
        terminal = StreamProducerTerminal(exception=None)
        try:
            async for detail in iterator:
                try:
                    self._record_queue_saturation(queue=queue, context=context)
                    await asyncio.wait_for(
                        queue.put(detail),
                        timeout=self._policy.send_timeout_seconds,
                    )
                except TimeoutError as exc:
                    self._record_queue_saturation(queue=queue, context=context)
                    terminal = StreamProducerTerminal(
                        exception=TimeoutError(STREAM_SLOW_CONSUMER_MESSAGE)
                    )
                    raise exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            terminal = StreamProducerTerminal(exception=exc)
        finally:
            await iterator.aclose()
            current_task = asyncio.current_task()
            if current_task is None or not current_task.cancelling():
                try:
                    queue.put_nowait(terminal)
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    queue.put_nowait(terminal)

    def _build_event(
        self,
        *,
        stream_id: str,
        sequence: int,
        context: StreamExecutionContext,
        detail: BaseModel,
    ) -> StreamEventEnvelope[T_StreamDetail]:
        """构建规范化事件信封。"""

        return StreamEventEnvelope[T_StreamDetail](
            header=StreamEventHeader(
                stream_id=stream_id,
                event_id=str(uuid.uuid4()),
                sequence=sequence,
                event_kind=str(getattr(detail, "kind")),
                schema_version=STREAM_SCHEMA_VERSION,
                request_id=context.request_id,
                trace_id=context.trace_id,
            ),
            detail=cast(T_StreamDetail, detail),
        )

    def _build_fault_event(
        self,
        *,
        stream_id: str,
        sequence: int,
        context: StreamExecutionContext,
        error_code: CoreErrorCode,
        message: str,
        retryable: bool,
        close_reason: StreamCloseReason,
    ) -> StreamEventEnvelope[T_StreamDetail]:
        """构建流故障终止事件。"""

        return self._build_event(
            stream_id=stream_id,
            sequence=sequence,
            context=context,
            detail=StreamFaultDetail(
                error_code=error_code,
                message=message,
                retryable=retryable,
                close_reason=close_reason,
            ),
        )

    def _validate_event(
        self,
        event: StreamEventEnvelope[T_StreamDetail],
    ) -> StreamEventEnvelope[T_StreamDetail]:
        """执行事件联合与最大字节校验。"""

        validated = self._event_adapter.validate_python(event)
        event_bytes = len(validated.model_dump_json().encode(STREAM_EVENT_TEXT_ENCODING))
        if event_bytes > self._policy.max_event_bytes:
            raise HttpFaultException(
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                error_code=CoreErrorCode.REQUEST_PAYLOAD_TOO_LARGE,
                message=STREAM_EVENT_SIZE_LIMIT_MESSAGE,
            )
        return validated

    def _record_queue_saturation(
        self,
        *,
        queue: asyncio.Queue[T_StreamDetail | StreamProducerTerminal],
        context: StreamExecutionContext,
    ) -> None:
        """记录有界队列饱和度，不包含会话标识。"""

        if self._queue_saturation_observer is None:
            return
        self._queue_saturation_observer.record(
            transport=context.transport,
            ratio=queue.qsize() / self._policy.queue_capacity,
        )
