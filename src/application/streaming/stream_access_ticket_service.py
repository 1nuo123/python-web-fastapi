"""短期单次流访问票据服务。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketEnvelope,
    StreamAccessTicketHeader,
    StreamAccessTicketIssuedDetail,
    StreamAccessTicketRecord,
    StreamAccessTicketResultKind,
    StreamTicketConsumptionRequest,
)

STREAM_TICKET_RANDOM_BYTES = 32
STREAM_TICKET_DIGEST_ENCODING = "utf-8"


class StreamAccessTicketService:
    """流访问票据签发与消费服务。"""

    def __init__(self, *, state_store: StreamStateStorePort, ttl_seconds: int) -> None:
        """初始化票据服务。

        :param state_store: 流状态存储。
        :type state_store: StreamStateStorePort
        :param ttl_seconds: 票据有效期秒数。
        :type ttl_seconds: int
        """

        self._state_store = state_store
        self._ttl_seconds = ttl_seconds

    async def issue(
        self,
        *,
        subject_id: str,
        operation_name: str,
        client_ip: str | None,
        current_time: datetime | None = None,
    ) -> StreamAccessTicketEnvelope:
        """签发短期单次票据。

        :param subject_id: 绑定主体。
        :type subject_id: str
        :param operation_name: 绑定操作。
        :type operation_name: str
        :param client_ip: 可选绑定客户端 IP。
        :type client_ip: str | None
        :param current_time: 可注入当前时间。
        :type current_time: datetime | None
        :returns: 仅包含一次明文票据的签发结果。
        :rtype: StreamAccessTicketEnvelope
        """

        issued_at = current_time or datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)
        ticket = secrets.token_urlsafe(STREAM_TICKET_RANDOM_BYTES)
        await self._state_store.store_ticket(
            StreamAccessTicketRecord(
                ticket_digest=self.digest(ticket),
                subject_id=subject_id,
                operation_name=operation_name,
                client_ip=client_ip,
                expires_at=expires_at,
            )
        )
        return StreamAccessTicketEnvelope(
            header=StreamAccessTicketHeader(
                subject_id=subject_id,
                operation_name=operation_name,
                result_kind=StreamAccessTicketResultKind.ISSUED,
            ),
            detail=StreamAccessTicketIssuedDetail(
                ticket=ticket,
                client_ip=client_ip,
                expires_at=expires_at,
            ),
        )

    async def consume(
        self,
        *,
        ticket: str,
        subject_id: str,
        operation_name: str,
        client_ip: str | None,
        current_time: datetime | None = None,
    ) -> bool:
        """校验并原子消费票据。

        :param ticket: 票据明文。
        :type ticket: str
        :param subject_id: 当前主体。
        :type subject_id: str
        :param operation_name: 当前操作。
        :type operation_name: str
        :param client_ip: 当前客户端 IP。
        :type client_ip: str | None
        :param current_time: 可注入当前时间。
        :type current_time: datetime | None
        :returns: 票据匹配且首次消费时返回 ``True``。
        :rtype: bool
        """

        return await self._state_store.consume_ticket(
            StreamTicketConsumptionRequest(
                ticket_digest=self.digest(ticket),
                subject_id=subject_id,
                operation_name=operation_name,
                client_ip=client_ip,
                consumed_at=current_time or datetime.now(UTC),
            )
        )

    def digest(self, ticket: str) -> str:
        """计算票据摘要。

        :param ticket: 票据明文。
        :type ticket: str
        :returns: SHA-256 十六进制摘要。
        :rtype: str
        """

        return hashlib.sha256(ticket.encode(STREAM_TICKET_DIGEST_ENCODING)).hexdigest()
