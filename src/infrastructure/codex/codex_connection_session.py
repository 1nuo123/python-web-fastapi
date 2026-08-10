"""独立于单操作流处理器的 Codex 长期双向连接会话。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionFrameTooLargeError,
    CodexConnectionSessionInactiveError,
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

    def __post_init__(self) -> None:
        """拒绝无法形成有效有界会话的策略。"""

        if self.outbound_queue_capacity <= 0:
            raise ValueError("Codex长期连接发送队列容量必须大于零。")
        if self.max_frame_bytes <= 0:
            raise ValueError("Codex长期连接帧上限必须大于零。")
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
    ) -> None:
        """初始化长期连接会话。"""

        self._transport = transport
        self._inbound_handler = inbound_handler
        self._policy = policy
        self._outbound_queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=policy.outbound_queue_capacity
        )
        self._running = False

    @property
    def running(self) -> bool:
        """返回会话当前是否处于运行状态。"""

        return self._running

    async def send(self, frame: CodexConnectionFrame) -> None:
        """校验并有界入队一个出站帧。"""

        if not self._running:
            raise CodexConnectionSessionInactiveError("Codex长期连接会话已经停止。")
        payload = frame.model_dump_json()
        self._validate_frame_size(payload)
        try:
            await asyncio.wait_for(
                self._outbound_queue.put(payload),
                timeout=self._policy.send_enqueue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise CodexConnectionSlowConsumerError("Codex长期连接发送队列已满。") from exc

    async def run(self, *, shutdown_event: asyncio.Event) -> None:
        """运行独立读写循环，直到传输关闭、失败或收到停机通知。"""

        if self._running:
            raise RuntimeError("同一个Codex长期连接会话不能重复运行。")
        self._running = True
        receiver = asyncio.create_task(self._receive_loop())
        sender = asyncio.create_task(self._send_loop())
        shutdown_waiter = asyncio.create_task(shutdown_event.wait())
        tasks = (receiver, sender, shutdown_waiter)
        close_code = CODEX_CONNECTION_NORMAL_CLOSE_CODE
        close_reason = CODEX_CONNECTION_NORMAL_CLOSE_REASON
        failure: BaseException | None = None
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is shutdown_waiter:
                    continue
                try:
                    task.result()
                except CodexConnectionTransportClosed:
                    continue
                except BaseException as exc:
                    failure = exc
                    close_code = CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_CODE
                    close_reason = CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_REASON
                    break
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._running = False
            await self._transport.close(code=close_code, reason=close_reason)
        if failure is not None:
            raise failure

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
            payload = await self._outbound_queue.get()
            try:
                await self._transport.send_text(payload)
            finally:
                self._outbound_queue.task_done()

    def _validate_frame_size(self, payload: str) -> None:
        """按UTF-8字节数执行双向frame上限。"""

        if len(payload.encode("utf-8")) > self._policy.max_frame_bytes:
            raise CodexConnectionFrameTooLargeError("Codex长期连接帧超过配置上限。")
