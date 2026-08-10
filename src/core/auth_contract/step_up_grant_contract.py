"""增强授权用途核心契约。"""

from __future__ import annotations

from enum import StrEnum


class StepUpGrantPurpose(StrEnum):
    """需要密码再验证的一次性高风险操作。"""

    CODEX_HIGH_RISK_APPROVAL = "codex.high_risk_approval"
    CODEX_HOST_REVOKE = "codex.host.revoke"
