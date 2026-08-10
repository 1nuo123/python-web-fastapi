"""Windows Agent 首次设备授权与配置落盘流程。"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import hashlib
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import rtoml

from src.application.ports.agent_device_key_store_port import AgentDeviceKeyStorePort
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateDetail,
    DeviceAuthorizationCreateRequestEnvelope,
    DeviceAuthorizationEnvelope,
    DeviceAuthorizationIssuedDetail,
    DeviceAuthorizationPollRequest,
    DeviceAuthorizationPollRequestEnvelope,
    DeviceAuthorizationRequestHeader,
    DeviceAuthorizationState,
    DeviceAuthorizationStatusDetail,
    DeviceEnrollmentCanonicalMessage,
)
from src.infrastructure.codex_agent.agent_configuration import (
    AgentProcessSettings,
    AgentProtocolSettings,
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
)
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
)

DEVICE_AUTHORIZATION_CREATE_PATH = "/internal/codex-agents/device-authorizations"
DEVICE_AUTHORIZATION_POLL_PATH = "/internal/codex-agents/device-authorizations/poll"
WINDOWS_MESSAGE_BOX_INFORMATION = 0x40


class WindowsEnrollmentUi:
    """使用 Windows 原生对话框展示短期用户码，避免进入日志。"""

    def show(self, *, verification_uri: str, user_code: str, fingerprint: str) -> None:
        if sys.platform != "win32":
            raise OSError("Agent首次设置只支持Windows交互会话。")
        webbrowser.open(verification_uri)
        message = (
            f"请在浏览器中批准这台电脑。\n\n用户码：{user_code}"
            f"\n设备指纹：{fingerprint}\n\n此窗口关闭后仍会等待批准。"
        )
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "Codex Remote Agent 设备授权",
            WINDOWS_MESSAGE_BOX_INFORMATION,
        )


class CodexAgentSetupUsecase:
    """生成设备密钥、完成授权轮询并写入非敏感 Agent 配置。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        key_store: AgentDeviceKeyStorePort,
        ui: WindowsEnrollmentUi,
        acl_enforcer: WindowsCurrentUserAclEnforcer,
    ) -> None:
        self._client = client
        self._key_store = key_store
        self._ui = ui
        self._acl_enforcer = acl_enforcer

    async def execute(
        self,
        *,
        config_path: Path,
        api_url: str,
        websocket_url: str,
        verification_url: str | None = None,
        display_name: str,
        platform: str,
        expected_codex_version: str,
        schema_digest: str,
        workspace: AgentWorkspaceSettings,
    ) -> CodexHostAgentSettings:
        key_id = uuid4()
        public_key = self._key_store.generate(key_id)
        try:
            issued = await self._create_authorization(
                api_url=api_url,
                key_id=key_id,
                public_key=public_key,
                display_name=display_name,
                platform=platform,
            )
            fingerprint = hashlib.sha256(public_key).hexdigest()
            issued_detail = issued.detail
            if not isinstance(issued_detail, DeviceAuthorizationIssuedDetail):
                raise ValueError("设备授权创建未返回issued扩展。")
            resolved_verification_uri = issued_detail.verification_uri
            if verification_url is not None:
                query_separator = "&" if "?" in verification_url else "?"
                resolved_verification_uri = (
                    f"{verification_url}{query_separator}"
                    f"user_code={quote(issued_detail.user_code, safe='')}"
                )
            self._ui.show(
                verification_uri=resolved_verification_uri,
                user_code=issued_detail.user_code,
                fingerprint=fingerprint,
            )
            status = await self._poll_until_terminal(api_url=api_url, issued=issued)
            if status.state != DeviceAuthorizationState.APPROVED or status.host_id is None:
                raise PermissionError("设备授权未获批准。")
            if status.key_id != key_id:
                raise PermissionError("服务端批准的设备key与本机密钥不一致。")
            settings = CodexHostAgentSettings(
                agent=AgentProcessSettings(
                    host_id=status.host_id,
                    key_id=key_id,
                    display_name=display_name,
                    control_plane_url=websocket_url,
                    control_plane_api_url=api_url,
                    state_database=config_path.parent / "state.sqlite",
                ),
                protocol=AgentProtocolSettings(
                    agent_schema_version=CodexConnectionProtocolVersion.V2,
                    expected_codex_version=expected_codex_version,
                    app_server_schema_digest=schema_digest,
                ),
                workspaces=[workspace],
            )
            config_path.parent.mkdir(parents=True, exist_ok=True)
            rtoml.dump(settings.model_dump(mode="json", exclude_none=True), config_path)
            self._acl_enforcer.enforce(config_path)
            return settings
        except BaseException:
            self._key_store.delete(key_id)
            raise

    async def _create_authorization(
        self,
        *,
        api_url: str,
        key_id: UUID,
        public_key: bytes,
        display_name: str,
        platform: str,
    ) -> DeviceAuthorizationEnvelope:
        response = await self._client.post(
            f"{api_url.rstrip('/')}{DEVICE_AUTHORIZATION_CREATE_PATH}",
            json=self._build_create_request(
                key_id=key_id,
                public_key=public_key,
                display_name=display_name,
                platform=platform,
            ).model_dump(mode="json"),
        )
        response.raise_for_status()
        envelope = DeviceAuthorizationEnvelope.model_validate(response.json())
        if not isinstance(envelope.detail, DeviceAuthorizationIssuedDetail):
            raise ValueError("设备授权创建未返回issued扩展。")
        return envelope

    def _build_create_request(
        self,
        *,
        key_id: UUID,
        public_key: bytes,
        display_name: str,
        platform: str,
    ) -> DeviceAuthorizationCreateRequestEnvelope:
        nonce = base64.urlsafe_b64encode(uuid4().bytes + uuid4().bytes).decode("ascii")
        message = DeviceEnrollmentCanonicalMessage(
            key_id=key_id,
            display_name=display_name,
            platform=platform,
            public_key_fingerprint=hashlib.sha256(public_key).hexdigest(),
            nonce=nonce,
        )
        return DeviceAuthorizationCreateRequestEnvelope(
            header=DeviceAuthorizationRequestHeader(request_id=uuid4()),
            detail=DeviceAuthorizationCreateDetail(
                key_id=key_id,
                display_name=display_name,
                platform=platform,
                public_key_base64=base64.b64encode(public_key).decode("ascii"),
                nonce=nonce,
                nonce_signature_base64=base64.b64encode(
                    self._key_store.sign(key_id, message.canonical_bytes())
                ).decode("ascii"),
            ),
        )

    async def _poll_until_terminal(
        self,
        *,
        api_url: str,
        issued: DeviceAuthorizationEnvelope,
    ) -> DeviceAuthorizationStatusDetail:
        if not isinstance(issued.detail, DeviceAuthorizationIssuedDetail):
            raise ValueError("设备授权缺少轮询凭据。")
        while True:
            await asyncio.sleep(issued.detail.interval_seconds)
            response = await self._client.post(
                f"{api_url.rstrip('/')}{DEVICE_AUTHORIZATION_POLL_PATH}",
                json=DeviceAuthorizationPollRequestEnvelope(
                    header=DeviceAuthorizationRequestHeader(request_id=uuid4()),
                    detail=DeviceAuthorizationPollRequest(
                        enrollment_id=issued.header.enrollment_id,
                        device_code=issued.detail.device_code,
                    ),
                ).model_dump(mode="json"),
            )
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                continue
            response.raise_for_status()
            envelope = DeviceAuthorizationEnvelope.model_validate(response.json())
            if not isinstance(envelope.detail, DeviceAuthorizationStatusDetail):
                raise ValueError("设备授权轮询未返回status扩展。")
            if envelope.detail.state in {
                DeviceAuthorizationState.APPROVED,
                DeviceAuthorizationState.DENIED,
                DeviceAuthorizationState.EXPIRED,
                DeviceAuthorizationState.CANCELLED,
            }:
                return envelope.detail
