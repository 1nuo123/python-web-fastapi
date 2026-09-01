"""Codex App Server JSON-RPC 最小稳定契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

JsonRpcId: TypeAlias = int | str


class AppServerJsonRpcError(BaseModel):
    """App Server 返回的 JSON-RPC 错误。"""

    model_config = ConfigDict(extra="forbid")

    code: int
    message: str
    data: JsonValue | None = None


class AppServerProtocolMessage(BaseModel):
    """按字段方向分类前的 App Server 消息。"""

    # App Server is an upstream evolving protocol. Unknown envelope fields are
    # ignored here and surfaced only through the narrow adapter warning path;
    # Remote's own Agent Protocol v2 remains strict.
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: JsonRpcId | None = None
    method: str | None = None
    params: JsonValue | None = None
    result: JsonValue | None = None
    error: AppServerJsonRpcError | None = None
    emitted_at_ms: int | None = Field(default=None, alias="emittedAtMs", ge=0)


class AppServerRpcError(RuntimeError):
    """App Server 明确返回的 RPC 失败。"""

    def __init__(self, error: AppServerJsonRpcError) -> None:
        super().__init__(error.message)
        self.error = error


class AppServerProtocolError(ValueError):
    """App Server 输出违反 JSON-RPC 方向或结构。"""


class AppServerMessageTooLargeError(AppServerProtocolError):
    """App Server 单条 JSONL 消息超过 Agent 的固定容量边界。"""

    def __init__(self, max_line_bytes: int) -> None:
        super().__init__(f"App Server单条输出超过{max_line_bytes}字节上限。")
        self.max_line_bytes = max_line_bytes


class AppServerClientStoppedError(ConnectionError):
    """App Server stdout 读取循环已经停止。"""


class AppServerUnknownOutcomeError(TimeoutError):
    """mutation 已发送但 deadline 到期，结果不能安全推断。"""

    def __init__(self, method: str, operation_id: str | None) -> None:
        super().__init__(f"App Server方法{method}结果未知，禁止自动重放。")
        self.method = method
        self.operation_id = operation_id


class AppServerOverloadBudgetExceededError(TimeoutError):
    """App Server overload 有界重试预算已经耗尽。"""

    def __init__(self, method: str) -> None:
        super().__init__(f"App Server方法{method}过载重试预算已耗尽。")
        self.method = method


class AppServerLineReaderPort(Protocol):
    """App Server stdout 行读取边界。"""

    async def readline(self) -> bytes: ...


class AppServerLineWriterPort(Protocol):
    """App Server stdin 单写者边界。"""

    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...


class AppServerRpcClientPort(Protocol):
    """Agent 命令执行器使用的 App Server 请求边界。"""

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue: ...


@dataclass(frozen=True, slots=True)
class PendingAppServerRequest:
    """待关联请求的诊断元数据。"""

    method: str
    operation_id: str | None
