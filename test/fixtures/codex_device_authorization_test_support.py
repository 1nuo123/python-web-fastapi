"""Codex 设备授权与一次性连接票据测试支持。"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from src.api.endpoint_auth_access.contract_auth_access import BrowserTokenIssuePayload
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentCommandAckV2Detail,
    AgentCommandV2Detail,
    AgentEventAckV2Detail,
    AgentEventBatchV2Detail,
    AgentEventDetail,
    AgentEventRecord,
    AgentHelloAckV2Detail,
    AgentHelloV2Detail,
    AgentProtocolV2Detail,
    AgentProtocolV2Envelope,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerDefaultCatalog,
)
from src.core.codex_contract.connection_session_contract import CodexConnectionFrame
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateDetail,
    DeviceAuthorizationCreateRequestEnvelope,
    DeviceAuthorizationDecideRequest,
    DeviceAuthorizationDecideRequestEnvelope,
    DeviceAuthorizationDecision,
    DeviceAuthorizationEnvelope,
    DeviceAuthorizationIssuedDetail,
    DeviceAuthorizationPollRequest,
    DeviceAuthorizationPollRequestEnvelope,
    DeviceAuthorizationRequestHeader,
    DeviceAuthorizationState,
    DeviceAuthorizationStatusDetail,
    DeviceEnrollmentCanonicalMessage,
)
from src.core.codex_contract.device_key_contract import (
    AgentConnectionTicketResponse,
    DeviceChallengeCanonicalMessage,
    DeviceChallengeIssue,
    DeviceChallengeIssueRequest,
    DeviceChallengeIssueRequestEnvelope,
    DeviceChallengeProof,
    DeviceChallengeProofRequestEnvelope,
    DeviceChallengeRequestHeader,
    DeviceKeyState,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.infrastructure.codex.agent_protocol_codec import AgentProtocolCodecRegistry
from src.infrastructure.persistence.orm_model.codex_host_device_key_orm_model import (
    CodexHostDeviceKeyOrmModel,
)

TEST_BROWSER_ORIGIN = "http://testserver"
TEST_DEVICE_DISPLAY_NAME = "Personal Windows"
TEST_DEVICE_PLATFORM = "windows"
TEST_DEVICE_NONCE_BYTES = 32
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "admin"
TEST_IDEMPOTENCY_KEY = "device-authorization-test"
NORMAL_WEBSOCKET_CLOSE_CODE = 1000
FROZEN_CODEX_VERSION = "0.145.0"
FROZEN_APP_SERVER_SCHEMA_DIGEST = "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109"


@dataclass(frozen=True, slots=True)
class AuthorizedAgentDevice:
    """测试持有的设备私钥与服务端身份引用。"""

    host_id: UUID
    key_id: UUID
    private_key: Ed25519PrivateKey


@dataclass(frozen=True, slots=True)
class AuthorizedAgentV2Connection:
    """测试持有的 v2 连接代次与事件序号域。"""

    device: AuthorizedAgentDevice
    agent_event_epoch: UUID
    connection_epoch: int
    revocation_generation: int


class CodexDeviceAuthorizationTestSupport:
    """通过公开 v2 接口建立 Agent 测试身份。"""

    @classmethod
    def authorize_device(cls, client: TestClient) -> AuthorizedAgentDevice:
        """执行注册证明、用户批准和 Agent 轮询完整流程。"""

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_id = uuid4()
        nonce = base64.urlsafe_b64encode(secrets.token_bytes(TEST_DEVICE_NONCE_BYTES)).decode(
            "ascii"
        )
        enrollment_message = DeviceEnrollmentCanonicalMessage(
            key_id=key_id,
            display_name=TEST_DEVICE_DISPLAY_NAME,
            platform=TEST_DEVICE_PLATFORM,
            public_key_fingerprint=hashlib.sha256(public_key).hexdigest(),
            nonce=nonce,
        )
        create_response = client.post(
            "/internal/codex-agents/device-authorizations",
            json=DeviceAuthorizationCreateRequestEnvelope(
                header=DeviceAuthorizationRequestHeader(request_id=uuid4()),
                detail=DeviceAuthorizationCreateDetail(
                    key_id=key_id,
                    display_name=TEST_DEVICE_DISPLAY_NAME,
                    platform=TEST_DEVICE_PLATFORM,
                    public_key_base64=base64.b64encode(public_key).decode("ascii"),
                    nonce=nonce,
                    nonce_signature_base64=base64.b64encode(
                        private_key.sign(enrollment_message.canonical_bytes())
                    ).decode("ascii"),
                ),
            ).model_dump(mode="json"),
        )
        create_response.raise_for_status()
        issued = DeviceAuthorizationEnvelope.model_validate(create_response.json())
        if not isinstance(issued.detail, DeviceAuthorizationIssuedDetail):
            raise AssertionError("设备授权创建未返回一次性授权代码。")

        access_token = cls.issue_browser_access_token(client)
        decision_response = client.post(
            "/codex/device-authorizations/decisions",
            headers={"Authorization": f"Bearer {access_token}"},
            json=DeviceAuthorizationDecideRequestEnvelope(
                header=DeviceAuthorizationRequestHeader(request_id=uuid4()),
                detail=DeviceAuthorizationDecideRequest(
                    enrollment_id=issued.header.enrollment_id,
                    user_code=issued.detail.user_code,
                    decision=DeviceAuthorizationDecision.APPROVE,
                    idempotency_key=TEST_IDEMPOTENCY_KEY,
                ),
            ).model_dump(mode="json"),
        )
        decision_response.raise_for_status()

        poll_response = client.post(
            "/internal/codex-agents/device-authorizations/poll",
            json=DeviceAuthorizationPollRequestEnvelope(
                header=DeviceAuthorizationRequestHeader(request_id=uuid4()),
                detail=DeviceAuthorizationPollRequest(
                    enrollment_id=issued.header.enrollment_id,
                    device_code=issued.detail.device_code,
                ),
            ).model_dump(mode="json"),
        )
        poll_response.raise_for_status()
        polled = DeviceAuthorizationEnvelope.model_validate(poll_response.json())
        if not isinstance(polled.detail, DeviceAuthorizationStatusDetail):
            raise AssertionError("设备授权轮询未返回状态扩展。")
        if (
            polled.detail.state is not DeviceAuthorizationState.APPROVED
            or polled.detail.host_id is None
            or polled.detail.key_id != key_id
        ):
            raise AssertionError("设备授权未返回已激活的 v2 设备身份。")
        return AuthorizedAgentDevice(
            host_id=polled.detail.host_id,
            key_id=key_id,
            private_key=private_key,
        )

    @classmethod
    def provision_active_key(
        cls,
        *,
        app: FastAPI,
        host_id: UUID,
        owner_subject_id: str,
    ) -> AuthorizedAgentDevice:
        """为已由测试创建的主机持久化活跃 Ed25519 key。"""

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_id = uuid4()
        now = datetime.now(UTC)
        unit_of_work = app.state.container.resource_mount.create_unit_of_work()
        try:
            unit_of_work.get_session().add(
                CodexHostDeviceKeyOrmModel(
                    key_id=key_id,
                    enrollment_id=uuid4(),
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    public_key=public_key,
                    fingerprint=hashlib.sha256(public_key).hexdigest(),
                    state=DeviceKeyState.ACTIVE.value,
                    version=1,
                    activated_at=now,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
        return AuthorizedAgentDevice(
            host_id=host_id,
            key_id=key_id,
            private_key=private_key,
        )

    @classmethod
    def issue_connection_ticket(
        cls,
        client: TestClient,
        device: AuthorizedAgentDevice,
    ) -> AgentConnectionTicketResponse:
        """用一次性挑战和设备签名换取 WSS ticket。"""

        challenge_response = client.post(
            "/internal/codex-agents/device-challenges",
            json=DeviceChallengeIssueRequestEnvelope(
                header=DeviceChallengeRequestHeader(request_id=uuid4()),
                detail=DeviceChallengeIssueRequest(
                    host_id=device.host_id,
                    key_id=device.key_id,
                ),
            ).model_dump(mode="json"),
        )
        challenge_response.raise_for_status()
        challenge = DeviceChallengeIssue.model_validate(challenge_response.json())
        canonical = DeviceChallengeCanonicalMessage(
            challenge_id=challenge.challenge_id,
            host_id=challenge.host_id,
            key_id=challenge.key_id,
            nonce=challenge.nonce,
            audience=challenge.audience,
            issued_at=challenge.issued_at,
            expires_at=challenge.expires_at,
        )
        ticket_response = client.post(
            "/internal/codex-agents/connection-tickets",
            json=DeviceChallengeProofRequestEnvelope(
                header=DeviceChallengeRequestHeader(request_id=uuid4()),
                detail=DeviceChallengeProof(
                    challenge_id=challenge.challenge_id,
                    host_id=device.host_id,
                    key_id=device.key_id,
                    signature_base64=base64.b64encode(
                        device.private_key.sign(canonical.canonical_bytes())
                    ).decode("ascii"),
                ),
            ).model_dump(mode="json"),
        )
        ticket_response.raise_for_status()
        return AgentConnectionTicketResponse.model_validate(ticket_response.json())

    @classmethod
    def issue_browser_access_token(cls, client: TestClient) -> str:
        """签发测试管理员浏览器 access token。"""

        response = client.post(
            "/auth/browser/token",
            headers={"Origin": TEST_BROWSER_ORIGIN},
            json={
                "username": TEST_ADMIN_USERNAME,
                "password": TEST_ADMIN_PASSWORD,
            },
        )
        if response.status_code != HTTPStatus.OK:
            raise AssertionError("测试管理员浏览器令牌签发失败。")
        envelope = ResponseEnvelope[BrowserTokenIssuePayload].model_validate(response.json())
        return envelope.data.access_token

    @classmethod
    def frame_v1(cls, message_type: str, payload: BaseModel) -> str:
        """把强类型 v1 payload 编码为控制通道 frame。"""

        return CodexConnectionFrame(
            message_id=str(uuid4()),
            message_type=message_type,
            payload=payload.model_dump(mode="json"),
        ).model_dump_json()

    @classmethod
    def connect_v2(
        cls,
        websocket: WebSocketTestSession,
        device: AuthorizedAgentDevice,
    ) -> AuthorizedAgentV2Connection:
        """发送完整 v2 hello 并校验服务端确认。"""

        event_epoch = uuid4()
        websocket.send_text(
            cls.frame_v2(
                device=device,
                detail=AgentHelloV2Detail(
                    agent_version="2.0.0",
                    codex_version=FROZEN_CODEX_VERSION,
                    app_server_schema_digest=FROZEN_APP_SERVER_SCHEMA_DIGEST,
                    capabilities=AppServerDefaultCatalog().build_capabilities(),
                    agent_event_epoch=event_epoch,
                ),
            )
        )
        envelope = cls.receive_v2_envelope(websocket)
        if not isinstance(envelope.detail, AgentHelloAckV2Detail):
            raise AssertionError("Agent v2测试连接未收到hello_ack。")
        if envelope.detail.acknowledged_event_epoch != event_epoch:
            raise AssertionError("Agent v2测试连接事件epoch未被正确确认。")
        return AuthorizedAgentV2Connection(
            device=device,
            agent_event_epoch=event_epoch,
            connection_epoch=envelope.detail.connection_epoch,
            revocation_generation=envelope.detail.revocation_generation,
        )

    @classmethod
    def frame_v2(
        cls,
        *,
        device: AuthorizedAgentDevice,
        detail: AgentProtocolV2Detail,
    ) -> str:
        """把强类型 v2 detail 编码为长期连接 transport frame。"""

        frame = AgentProtocolCodecRegistry().encode_v2(
            host_id=device.host_id,
            key_id=device.key_id,
            message_id=uuid4(),
            detail=detail,
        )
        return frame.model_dump_json()

    @classmethod
    def receive_v2_envelope(
        cls,
        websocket: WebSocketTestSession,
    ) -> AgentProtocolV2Envelope:
        """接收并校验 v2 transport frame。"""

        frame = CodexConnectionFrame.model_validate_json(websocket.receive_text())
        decoded = AgentProtocolCodecRegistry().decode(frame)
        if decoded.v2 is None:
            raise AssertionError("Agent v2测试连接收到了非v2 frame。")
        return decoded.v2

    @classmethod
    def send_v2_event(
        cls,
        websocket: WebSocketTestSession,
        connection: AuthorizedAgentV2Connection,
        detail: AgentEventDetail,
        *,
        sequence: int,
        app_server_instance_id: UUID,
    ) -> None:
        """发送单事件批次并消费累计 ACK，避免干扰后续命令。"""

        record = AgentEventRecord(
            agent_event_epoch=connection.agent_event_epoch,
            seq=sequence,
            event_id=uuid4(),
            app_server_instance_id=app_server_instance_id,
            detail=detail,
        )
        websocket.send_text(
            cls.frame_v2(
                device=connection.device,
                detail=AgentEventBatchV2Detail(
                    agent_event_epoch=connection.agent_event_epoch,
                    first_seq=sequence,
                    last_seq=sequence,
                    events=(record,),
                ),
            )
        )
        envelope = cls.receive_v2_envelope(websocket)
        if not isinstance(envelope.detail, AgentEventAckV2Detail):
            raise AssertionError("Agent v2事件未收到累计ACK。")
        if envelope.detail.after_seq != sequence:
            raise AssertionError("Agent v2事件累计ACK序号不匹配。")

    @classmethod
    def receive_v2_command(
        cls,
        websocket: WebSocketTestSession,
    ) -> AgentCommandV2Detail:
        """接收并校验一个 v2 command。"""

        envelope = cls.receive_v2_envelope(websocket)
        if not isinstance(envelope.detail, AgentCommandV2Detail):
            raise AssertionError("Agent v2测试连接未收到command。")
        return envelope.detail

    @classmethod
    def acknowledge_v2_command(
        cls,
        websocket: WebSocketTestSession,
        connection: AuthorizedAgentV2Connection,
        command: AgentCommandV2Detail,
    ) -> None:
        """确认一个已经由 Agent 完成副作用的 v2 命令。"""

        websocket.send_text(
            cls.frame_v2(
                device=connection.device,
                detail=AgentCommandAckV2Detail(
                    command_id=command.header.command_id,
                    operation_id=command.header.operation_id,
                    state="executing",
                    replayed=False,
                    recovery_required=False,
                ),
            )
        )

    @classmethod
    def receive_v1_command(
        cls,
        websocket: WebSocketTestSession,
    ) -> CodexAgentCommand:
        """接收并验证一个 v1 command frame。"""

        frame = CodexConnectionFrame.model_validate_json(websocket.receive_text())
        if frame.message_type != "command":
            raise AssertionError("Agent测试连接未收到command frame。")
        return CodexAgentCommand.model_validate(frame.payload)

    @classmethod
    def acknowledge_v1_command(
        cls,
        websocket: WebSocketTestSession,
        command: CodexAgentCommand,
    ) -> None:
        """确认一个 v1 Agent command。"""

        websocket.send_text(
            cls.frame_v1(
                "command.ack",
                CodexAgentCommandAck(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    state="accepted",
                    replayed=False,
                ),
            )
        )

    @classmethod
    def close_websocket(cls, websocket: WebSocketTestSession) -> None:
        """关闭测试 WebSocket 并确认服务端完成资源回收。"""

        websocket.close()
        try:
            websocket.receive_text()
        except WebSocketDisconnect as exc:
            if exc.code != NORMAL_WEBSOCKET_CLOSE_CODE:
                raise AssertionError("Agent WebSocket未正常关闭。") from exc
            return
        raise AssertionError("Agent WebSocket关闭后仍返回了消息。")
