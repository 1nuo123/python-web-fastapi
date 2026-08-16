"""应用层发布稳定 Codex 产品事件的端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot


class CodexRealtimeEventPort(Protocol):
    """发布不包含原始 JSON-RPC 的业务终态。"""

    async def publish_approval_resolved(
        self,
        approval: CodexApprovalAuditSnapshot,
    ) -> None: ...

    async def publish_thread_updated(
        self,
        thread: CodexThreadIndexSnapshot,
        *,
        occurred_at: datetime,
    ) -> None: ...
