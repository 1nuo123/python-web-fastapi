"""使用共享异步 HTTP client 获取 Agent 一次性连接票据。"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from urllib.parse import urljoin
from uuid import UUID, uuid4

import httpx

from src.application.ports.agent_connection_ticket_provider_port import (
    AgentConnectionTicketProviderPort,
)
from src.application.ports.agent_device_key_store_port import AgentDeviceKeyStorePort
from src.core.codex_contract.device_key_contract import (
    AgentConnectionTicketResponse,
    DeviceChallengeCanonicalMessage,
    DeviceChallengeIssue,
    DeviceChallengeIssueRequest,
    DeviceChallengeIssueRequestEnvelope,
    DeviceChallengeProof,
    DeviceChallengeProofRequestEnvelope,
    DeviceChallengeRequestHeader,
)
from src.domain.codex.codex_error_code import CodexErrorCode

DEVICE_CHALLENGE_PATH = "/internal/codex-agents/device-challenges"
DEVICE_CONNECTION_TICKET_PATH = "/internal/codex-agents/connection-tickets"


class AgentConnectionTicketProvider(AgentConnectionTicketProviderPort):
    """组合服务端挑战与本机设备签名，不拥有 HTTP client 生命周期。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        control_plane_api_url: str,
        key_store: AgentDeviceKeyStorePort,
    ) -> None:
        self._client = client
        self._control_plane_api_url = control_plane_api_url.rstrip("/") + "/"
        self._key_store = key_store

    async def binding_is_active(self, *, host_id: UUID, key_id: UUID) -> bool:
        """只有服务端明确拒绝旧身份才视为释放；网络或其它错误保持未知。"""
        response = await self._client.post(
            urljoin(self._control_plane_api_url, DEVICE_CHALLENGE_PATH.lstrip("/")),
            json=DeviceChallengeIssueRequestEnvelope(
                header=DeviceChallengeRequestHeader(request_id=uuid4()),
                detail=DeviceChallengeIssueRequest(host_id=host_id, key_id=key_id),
            ).model_dump(mode="json"),
        )
        if response.status_code == 404:
            payload = response.json()
            # 不把代理 404 或配置错误误判为已释放绑定。
            from src.domain.codex.codex_error_code import CodexErrorCode

            header = payload.get("header") if isinstance(payload, dict) else None
            if (
                isinstance(header, dict)
                and header.get("code") == CodexErrorCode.DEVICE_CHALLENGE_INVALID.value
            ):
                return False
        response.raise_for_status()
        DeviceChallengeIssue.model_validate(response.json())
        return True

    async def issue(self, *, host_id: UUID, key_id: UUID) -> AgentConnectionTicketResponse:
        proof = await self.prove(host_id=host_id, key_id=key_id)
        started = time.monotonic()
        proof_response = await self._client.post(
            urljoin(self._control_plane_api_url, DEVICE_CONNECTION_TICKET_PATH.lstrip("/")),
            json=DeviceChallengeProofRequestEnvelope(
                header=DeviceChallengeRequestHeader(request_id=uuid4()),
                detail=proof,
            ).model_dump(mode="json"),
        )
        logging.getLogger(__name__).info(
            "connection_stage phase=ticket_exchange duration_seconds=%.3f",
            time.monotonic() - started,
        )
        self._require_success(proof_response)
        return AgentConnectionTicketResponse.model_validate(proof_response.json())

    async def prove(self, *, host_id: UUID, key_id: UUID) -> DeviceChallengeProof:
        """签名现有挑战，调用方决定用于连接还是恢复同账号设备意图。"""
        started = time.monotonic()
        challenge_response = await self._client.post(
            urljoin(self._control_plane_api_url, DEVICE_CHALLENGE_PATH.lstrip("/")),
            json=DeviceChallengeIssueRequestEnvelope(
                header=DeviceChallengeRequestHeader(request_id=uuid4()),
                detail=DeviceChallengeIssueRequest(host_id=host_id, key_id=key_id),
            ).model_dump(mode="json"),
        )
        logging.getLogger(__name__).info(
            "connection_stage phase=challenge duration_seconds=%.3f", time.monotonic() - started
        )
        self._require_success(challenge_response)
        challenge = DeviceChallengeIssue.model_validate(challenge_response.json())
        started = time.monotonic()
        signature = await asyncio.to_thread(
            self._key_store.sign,
            key_id,
            DeviceChallengeCanonicalMessage(
                challenge_id=challenge.challenge_id,
                host_id=challenge.host_id,
                key_id=challenge.key_id,
                nonce=challenge.nonce,
                audience=challenge.audience,
                issued_at=challenge.issued_at,
                expires_at=challenge.expires_at,
            ).canonical_bytes(),
        )
        logging.getLogger(__name__).info(
            "connection_stage phase=sign duration_seconds=%.3f", time.monotonic() - started
        )
        return DeviceChallengeProof(
            challenge_id=challenge.challenge_id,
            host_id=host_id,
            key_id=key_id,
            signature_base64=base64.b64encode(signature).decode("ascii"),
        )

    @staticmethod
    def _require_success(response: httpx.Response) -> None:
        """仅识别受控错误合同；网关HTML、通用403不能代表设备密钥被撤销。"""
        if response.status_code in (401, 403, 404):
            try:
                payload = response.json()
            except ValueError:
                payload = None
            header = payload.get("header") if isinstance(payload, dict) else None
            code = header.get("code") if isinstance(header, dict) else None
            if code == CodexErrorCode.DEVICE_CHALLENGE_EXPIRED.value:
                raise ConnectionError("设备挑战过期，下轮重新签发。")
            if code == CodexErrorCode.DEVICE_CHALLENGE_INVALID.value:
                raise PermissionError("控制面明确拒绝设备身份或签名。")
        response.raise_for_status()
