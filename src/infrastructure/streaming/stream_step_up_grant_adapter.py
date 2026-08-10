"""基于通用单次流票据的增强授权适配器。"""

from __future__ import annotations

from src.application.ports.step_up_grant_port import StepUpGrantIssue, StepUpGrantPort
from src.application.streaming.stream_access_ticket_service import (
    StreamAccessTicketService,
)
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketIssuedDetail,
)


class StreamStepUpGrantAdapter(StepUpGrantPort):
    """将 purpose 映射为通用票据 operation_name。"""

    def __init__(self, *, ticket_service: StreamAccessTicketService) -> None:
        self._ticket_service = ticket_service

    async def issue(
        self,
        *,
        subject_id: str,
        purpose: StepUpGrantPurpose,
    ) -> StepUpGrantIssue:
        envelope = await self._ticket_service.issue(
            subject_id=subject_id,
            operation_name=purpose.value,
            client_ip=None,
        )
        if not isinstance(envelope.detail, StreamAccessTicketIssuedDetail):
            raise RuntimeError("增强授权票据签发未返回issued扩展。")
        return StepUpGrantIssue(
            token=envelope.detail.ticket,
            expires_at=envelope.detail.expires_at,
        )

    async def consume(
        self,
        *,
        token: str,
        subject_id: str,
        purpose: StepUpGrantPurpose,
    ) -> bool:
        return await self._ticket_service.consume(
            ticket=token,
            subject_id=subject_id,
            operation_name=purpose.value,
            client_ip=None,
        )
