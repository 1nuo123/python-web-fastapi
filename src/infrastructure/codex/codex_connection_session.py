"""独立于单操作流处理器的 Codex 长期双向连接会话。"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from typing import Final

from pydantic import ValidationError

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionEnd,
    CodexConnectionEndKind,
    CodexConnectionFrame,
    CodexConnectionFrameTooLargeError,
    CodexConnectionPresenceExpiredError,
    CodexConnectionQueueObservation,
    CodexConnectionSendTimeoutError,
    CodexConnectionSessionInactiveError,
    CodexConnectionShutdown,
    CodexConnectionSlowConsumerError,
    CodexConnectionTransportClosed,
    CodexConnectionTransportPort,
    CodexInboundFrameHandler,
    CodexOutboundFrameSenderPort,
)

CODEX_CONNECTION_NORMAL_CLOSE_CODE: Final = 1000
CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_CODE: Final = 1011
CODEX_CONNECTION_NORMAL_CLOSE_REASON: Final = "codex connection session closed"
CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_REASON: Final = "codex connection session failed"


@dataclass(frozen=True, slots=True)
class CodexConnectionSessionPolicy:
    """长期连接的容量策略。"""

    outbound_queue_capacity: int
    max_frame_bytes: int
    send_enqueue_timeout_seconds: float
    send_timeout_seconds: float = 10.0
    close_timeout_seconds: float = 3.0
    outbound_queue_max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        """拒绝无法形成有效有界会话的策略。"""

        if self.outbound_queue_capacity <= 0:
            raise ValueError("Codex长期连接发送队列容量必须大于零。")
        if self.max_frame_bytes <= 0:
            raise ValueError("Codex长期连接帧上限必须大于零。")
        if self.outbound_queue_max_bytes < 2 * self.max_frame_bytes:
            raise ValueError("发送队列字节预算必须至少容纳两个最大帧。")
        if min(self.send_timeout_seconds, self.close_timeout_seconds) <= 0:
            raise ValueError("发送与关闭预算必须大于零。")
        if self.send_enqueue_timeout_seconds <= 0:
            raise ValueError("Codex长期连接入队超时必须大于零。")


class CodexDuplexConnectionSession(CodexOutboundFrameSenderPort):
    """维护一个无固定运行时长、可并发收发多类消息的连接会话。"""

    def __init__(
        self,
        *,
        transport: CodexConnectionTransportPort,
        inbound_handler: CodexInboundFrameHandler,
        policy: CodexConnectionSessionPolicy,
        queue_observer: Callable[[CodexConnectionQueueObservation], None] | None = None,
    ) -> None:
        """初始化长期连接会话。"""

        self._transport = transport
        self._inbound_handler = inbound_handler
        self._policy = policy
        self._queue_observer = queue_observer
        self._queues: tuple[deque[tuple[str, int, float, asyncio.Future[None] | None]], ...] = (
            deque(),
            deque(),
            deque(),
        )
        self._queue_condition = asyncio.Condition()
        self._send_completions: set[asyncio.Future[None]] = set()
        self._queued_bytes = 0
        self._queued_count = 0
        self._schedule = (0, 0, 0, 0, 1, 1, 2)
        self._schedule_index = 0
        self._inflight_send: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(__name__)
        self._running = False
        self._requested_end: CodexConnectionEnd | None = None
        self._close_requested = asyncio.Event()

    def request_close(self, *, code: int, reason: str) -> None:
        """业务 owner 请求有原因的关闭；策略拒绝不能被普通停机覆盖。"""
        if self._requested_end is None or code == 1008:
            self._requested_end = CodexConnectionEnd(
                CodexConnectionEndKind.TRANSPORT_FAILURE
                if code in (1012, 1013)
                else CodexConnectionEndKind.LOCAL_STOP,
                code,
                reason,
            )
        self._close_requested.set()

    @property
    def running(self) -> bool:
        """返回会话当前是否处于运行状态。"""

        return self._running

    def restrict_message_limit(self, max_bytes: int) -> None:
        """握手只能收紧当前连接预算，重新连接重新协商。"""
        if max_bytes <= 0 or max_bytes > self._policy.max_frame_bytes:
            raise ValueError("有效消息预算不能超过本连接配置。")
        self._policy = replace(self._policy, max_frame_bytes=max_bytes)

    async def send(self, frame: CodexConnectionFrame) -> None:
        await self._enqueue(frame, None)

    async def send_and_wait(self, frame: CodexConnectionFrame) -> None:
        """查询在实际发送完成前持有预算；下一次源读取不得提前开始。"""
        completion = asyncio.get_running_loop().create_future()
        self._send_completions.add(completion)
        try:
            await self._enqueue(frame, completion)
            await completion
        finally:
            self._send_completions.discard(completion)
            if not completion.done():
                completion.cancel()

    async def _enqueue(
        self, frame: CodexConnectionFrame, completion: asyncio.Future[None] | None
    ) -> None:
        """校验并有界入队一个出站帧。"""

        if not self._running:
            raise CodexConnectionSessionInactiveError("Codex长期连接会话已经停止。")
        payload = frame.model_dump_json()
        self._validate_frame_size(payload)
        try:
            async with asyncio.timeout(self._policy.send_enqueue_timeout_seconds):
                priority = self._frame_priority(frame)
                size = len(payload.encode("utf-8"))
                byte_limit = self._policy.outbound_queue_max_bytes
                count_limit = self._policy.outbound_queue_capacity
                if priority != 0:
                    byte_limit -= self._policy.max_frame_bytes
                    count_limit = max(1, count_limit - min(8, count_limit // 4))
                async with self._queue_condition:
                    await self._queue_condition.wait_for(
                        lambda: (
                            not self._running
                            or (
                                self._queued_count < count_limit
                                and self._queued_bytes + size <= byte_limit
                            )
                        )
                    )
                    if not self._running:
                        raise CodexConnectionSessionInactiveError("连接已经停止。")
                    self._queues[priority].append(
                        (payload, size, asyncio.get_running_loop().time(), completion)
                    )
                    self._queued_bytes += size
                    self._queued_count += 1
                    self._queue_condition.notify_all()
        except TimeoutError as exc:
            self._logger.warning(
                "connection_queue_overloaded count=%s bytes=%s wait_seconds=%s",
                self._queued_count,
                self._queued_bytes,
                self._policy.send_enqueue_timeout_seconds,
            )
            self.request_close(code=1013, reason="queue_overloaded")
            raise CodexConnectionSlowConsumerError("Codex长期连接发送队列已满。") from exc

    async def run(self, *, shutdown_event: asyncio.Event) -> CodexConnectionEnd:
        """运行独立读写循环，直到传输关闭、失败或收到停机通知。"""

        if self._running:
            raise RuntimeError("同一个Codex长期连接会话不能重复运行。")
        self._running = True
        receiver = asyncio.create_task(self._receive_loop())
        sender = asyncio.create_task(self._send_loop())
        shutdown_waiter = asyncio.create_task(shutdown_event.wait())
        close_waiter = asyncio.create_task(self._close_requested.wait())
        tasks = (receiver, sender, shutdown_waiter, close_waiter)
        close_code = CODEX_CONNECTION_NORMAL_CLOSE_CODE
        close_reason = CODEX_CONNECTION_NORMAL_CLOSE_REASON
        failure: BaseException | None = None
        ended = CodexConnectionEnd(CodexConnectionEndKind.LOCAL_STOP, 1000, "local_stop")
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task not in done:
                    continue
                if task in (shutdown_waiter, close_waiter):
                    continue
                try:
                    task.result()
                except CodexConnectionTransportClosed as exc:
                    code = exc.close_code
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.TRANSPORT_FAILURE
                        if code in (None, 1006, 1011, 1012, 1013)
                        else CodexConnectionEndKind.REMOTE_CLOSE,
                        code,
                        exc.reason_code if code else "transport_closed",
                        exc,
                        phase="hello" if exc.reason_code == "hello_timeout" else exc.phase,
                        reason_code=exc.reason_code,
                    )
                except CodexConnectionPresenceExpiredError as exc:
                    close_code, close_reason = 1012, "presence_expired"
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.TRANSPORT_FAILURE, close_code, close_reason, exc
                    )
                except CodexConnectionFrameTooLargeError as exc:
                    close_code, close_reason = 1009, "message_too_large"
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.PROTOCOL_FAILURE, close_code, close_reason, exc
                    )
                except (PermissionError, ValueError) as exc:
                    close_code = 1008 if isinstance(exc, PermissionError) else 1002
                    close_reason = (
                        "authorization_rejected" if close_code == 1008 else "protocol_invalid"
                    )
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.PROTOCOL_FAILURE, close_code, close_reason, exc
                    )
                except CodexConnectionSlowConsumerError as exc:
                    close_code, close_reason = 1013, "overloaded"
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.TRANSPORT_FAILURE, close_code, close_reason, exc
                    )
                except (CodexConnectionSendTimeoutError, ConnectionError, OSError, EOFError) as exc:
                    close_code = 1011
                    close_reason = (
                        "send_timeout"
                        if isinstance(exc, CodexConnectionSendTimeoutError)
                        else "transport_failed"
                    )
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.TRANSPORT_FAILURE,
                        close_code,
                        close_reason,
                        exc,
                        phase="send" if task is sender else "receive",
                        reason_code=close_reason,
                    )
                except BaseException as exc:
                    failure = exc
                    close_code = CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_CODE
                    close_reason = CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_REASON
                    break
        finally:
            self._running = False
            for completion in tuple(self._send_completions):
                if not completion.done():
                    completion.set_exception(
                        CodexConnectionSessionInactiveError("查询所属连接已停止。")
                    )
            async with self._queue_condition:
                self._queue_condition.notify_all()
            if (
                isinstance(shutdown_event, CodexConnectionShutdown)
                and shutdown_event.end is not None
            ):
                self._requested_end = shutdown_event.end
            if self._requested_end is not None:
                ended = self._requested_end
                close_code = ended.close_code or 1000
                close_reason = ended.reason
            try:
                async with asyncio.timeout(self._policy.close_timeout_seconds):
                    await self._transport.close(code=close_code, reason=close_reason)
            except (OSError, TimeoutError):
                if failure is None and ended.kind == CodexConnectionEndKind.LOCAL_STOP:
                    ended = CodexConnectionEnd(
                        CodexConnectionEndKind.TRANSPORT_FAILURE, reason="close_failed"
                    )
            finally:
                cleanup_tasks = (*tasks, self._inflight_send) if self._inflight_send else tasks
                for task in cleanup_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                for queue in self._queues:
                    queue.clear()
                self._queued_bytes = self._queued_count = 0
                self._logger.info(
                    "connection_ended kind=%s phase=%s reason=%s code=%s",
                    ended.kind,
                    ended.phase,
                    ended.reason_code or ended.reason,
                    ended.close_code,
                )
        if failure is not None:
            raise failure
        return ended

    async def _receive_loop(self) -> None:
        """持续读取并分派多种入站消息，不绑定单次业务操作。"""

        while True:
            payload = await self._transport.receive_text()
            self._validate_frame_size(payload)
            try:
                frame = CodexConnectionFrame.model_validate_json(payload)
            except ValidationError as exc:
                raise ValueError("Codex长期连接入站帧不符合契约。") from exc
            await self._inbound_handler(frame, self)

    async def _send_loop(self) -> None:
        """使用单写者持续发送队列中的消息。"""

        while True:
            async with self._queue_condition:
                await self._queue_condition.wait_for(lambda: self._queued_count > 0)
                while not self._queues[self._schedule[self._schedule_index]]:
                    self._schedule_index = (self._schedule_index + 1) % len(self._schedule)
                priority = self._schedule[self._schedule_index]
                self._schedule_index = (self._schedule_index + 1) % len(self._schedule)
                payload, size, queued_at, completion = self._queues[priority].popleft()
                self._queued_count -= 1
                self._queued_bytes -= size
                self._queue_condition.notify_all()
            if self._queue_observer is not None:
                self._queue_observer(
                    CodexConnectionQueueObservation(
                        priority=priority,
                        wait_seconds=asyncio.get_running_loop().time() - queued_at,
                        queued_bytes=self._queued_bytes,
                    )
                )
            self._logger.debug(
                "connection_send priority=%s bytes=%s queue_wait_seconds=%.3f",
                priority,
                size,
                asyncio.get_running_loop().time() - queued_at,
            )
            self._inflight_send = asyncio.create_task(self._transport.send_text(payload))
            done, _ = await asyncio.wait(
                (self._inflight_send,), timeout=self._policy.send_timeout_seconds
            )
            if not done:
                # run() closes the socket BEFORE cancelling the in-flight send.
                raise CodexConnectionSendTimeoutError("连接发送超过预算。")
            await self._inflight_send
            self._inflight_send = None
            if completion is not None and not completion.done():
                completion.set_result(None)

    @staticmethod
    def _frame_priority(frame: CodexConnectionFrame) -> int:
        """只改变进程内调度；同类FIFO，控制预留容量，普通帧不会饥饿。"""
        detail = frame.payload.get("detail")
        message_type = detail.get("kind") if isinstance(detail, dict) else frame.message_type
        if message_type in {
            "hello",
            "hello_ack",
            "bounded_hello",
            "bounded_hello_ack",
            "heartbeat",
            "execution_lease",
            "execution_stopped",
        }:
            return 0
        if (
            message_type == "command_result"
            and isinstance(detail, dict)
            and isinstance(detail.get("result"), dict)
        ):
            return 2
        if message_type in {
            "command",
            "command_ack",
            "command_result",
            "event_ack",
            "replay_request",
        }:
            return 1
        return 2

    def _validate_frame_size(self, payload: str) -> None:
        """按UTF-8字节数执行双向frame上限。"""

        if len(payload.encode("utf-8")) > self._policy.max_frame_bytes:
            raise CodexConnectionFrameTooLargeError("Codex长期连接帧超过配置上限。")
