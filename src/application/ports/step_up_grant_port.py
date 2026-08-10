"""短时增强授权 grant 应用端口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose


@dataclass(frozen=True, slots=True)
class StepUpGrantIssue:
    token: str
    expires_at: datetime


class StepUpGrantPort(Protocol):
    async def issue(
        self,
        *,
        subject_id: str,
        purpose: StepUpGrantPurpose,
    ) -> StepUpGrantIssue: ...

    async def consume(
        self,
        *,
        token: str,
        subject_id: str,
        purpose: StepUpGrantPurpose,
    ) -> bool: ...
