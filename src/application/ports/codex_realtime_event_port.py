"""应用层发布稳定 Codex 产品事件的端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot


class CodexRealtimeEventPort(Protocol):
    """发布不包含原始 JSON-RPC 的业务终态。"""

    async def publish_approval_resolved(
        self,
        approval: CodexApprovalAuditSnapshot,
    ) -> None: ...
