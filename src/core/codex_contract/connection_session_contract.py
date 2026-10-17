"""Codex 长期双向连接会话契约。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

CODEX_CONNECTION_SCHEMA_VERSION: Final = "1.0"
CODEX_CONNECTION_FRAME_KIND: Final = "codex_connection_frame"
CODEX_LEASE_CONTINUITY_SUBPROTOCOL: Final = "codex-agent.v2.lease-continuity"


class CodexConnectionEndKind(StrEnum):
    """传输结束事实，不替代业务执行资格。"""

    LOCAL_STOP = "local_stop"
    REMOTE_CLOSE = "remote_close"
    TRANSPORT_FAILURE = "transport_failure"
    PROTOCOL_FAILURE = "protocol_failure"


@dataclass(frozen=True, slots=True)
class CodexConnectionEnd:
    """只在进程内传递的结束结果；异常及对端文本不直接进入日志。"""

    kind: CodexConnectionEndKind
    close_code: int | None = None
    reason: str = ""
    cause: BaseException | None = None

    def as_exception(self) -> CodexConnectionTransportClosed:
        error = CodexConnectionTransportClosed(self.reason or self.kind.value)
        error.close_code = self.close_code
        error.end_kind = self.kind
        error.__cause__ = self.cause
        return error


class CodexConnectionShutdown(asyncio.Event):
    """连接本地关闭信号与原因共用一个生命周期。"""

    def __init__(self) -> None:
        super().__init__()
        self.end: CodexConnectionEnd | None = None

    def request(self, code: int, reason: str) -> None:
        if self.end is None or code == 1008:
            self.end = CodexConnectionEnd(CodexConnectionEndKind.LOCAL_STOP, code, reason)
        self.set()


class CodexConnectionProtocolVersion(StrEnum):
    """长期连接可协商的产品协议版本。"""

    V1 = "1.0"
    V2 = "2.0"


class CodexConnectionFrame(BaseModel):
    """控制面与长期连接端点之间的稳定帧。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["codex_connection_frame"] = CODEX_CONNECTION_FRAME_KIND
    schema_version: Literal["1.0", "2.0"] = CODEX_CONNECTION_SCHEMA_VERSION
    message_id: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class CodexConnectionTransportClosed(ConnectionError):
    """底层长期连接已经正常关闭。"""

    close_code: int | None = None
    end_kind: CodexConnectionEndKind = CodexConnectionEndKind.TRANSPORT_FAILURE


class CodexConnectionSessionInactiveError(ConnectionError):
    """长期连接会话已经停止，当前不可继续发送。"""


class CodexConnectionFrameTooLargeError(ValueError):
    """长期连接帧超过配置上限。"""


class CodexConnectionSlowConsumerError(TimeoutError):
    """长期连接发送端无法在限定时间内接收更多帧。"""


class CodexHostOfflineError(ConnectionError):
    """目标 Agent 当前没有可用长期连接。"""


class CodexConnectionTransportPort(Protocol):
    """长期双向连接使用的最小传输端口。"""

    async def receive_text(self) -> str:
        """接收一个完整文本帧。"""

        ...

    async def send_text(self, payload: str) -> None:
        """发送一个完整文本帧。"""

        ...

    async def close(self, *, code: int, reason: str) -> None:
        """关闭底层连接。"""

        ...


class CodexOutboundFrameSenderPort(Protocol):
    """入站处理器可使用的有界发送端口。"""

    async def send(self, frame: CodexConnectionFrame) -> None:
        """将帧加入有界发送队列。"""

        ...


CodexInboundFrameHandler = Callable[
    [CodexConnectionFrame, CodexOutboundFrameSenderPort],
    Awaitable[None],
]
