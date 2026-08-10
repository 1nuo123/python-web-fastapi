"""Codex 浏览器实时票据应用端口。"""

from __future__ import annotations

from typing import Protocol


class CodexRealtimeTicketPort(Protocol):
    """一次性票据的签发与原子消费边界。"""

    def issue(self, *, subject_id: str, ttl_seconds: int) -> str: ...

    def consume(self, ticket: str) -> str | None: ...
