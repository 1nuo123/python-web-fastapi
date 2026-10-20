"""Windows Agent 首次设备授权与配置落盘流程。"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import hashlib
import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx

from src.infrastructure.codex_agent.agent_network_policy import AgentNetworkSettings

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
    DeviceAuthorizationRecoveryRequest,
    DeviceAuthorizationRecoveryResult,
)
from src.core.codex_contract.device_key_contract import (
    DeviceChallengeIssue,
    DeviceChallengeProof,
    DeviceChallengeCanonicalMessage,
)
from src.infrastructure.codex_agent.agent_enrollment_attempt_store import (
    AgentEnrollmentAttempt,
    AgentEnrollmentAttemptStore,
)
from src.infrastructure.codex_agent.agent_connection_policy import AgentControlConnectionPolicy
from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentConsumeDetail,
    CodexEnrollmentIntentConsumeRequestEnvelope,
    CodexEnrollmentIntentRequestHeader,
)
from src.infrastructure.codex_agent.agent_configuration import (
    AgentProcessSettings,
    AgentProtocolSettings,
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
)
from src.infrastructure.codex_agent.agent_config_store import AgentConfigStore
from src.infrastructure.codex_agent.agent_deployment_profile import (
    AgentDeploymentProfile,
)
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
)

DEVICE_AUTHORIZATION_CREATE_PATH = "/internal/codex-agents/device-authorizations"
DEVICE_AUTHORIZATION_POLL_PATH = "/internal/codex-agents/device-authorizations/poll"
ENROLLMENT_INTENT_CONSUME_PATH = "/internal/codex-agents/enrollment-intents/consume"
WINDOWS_MESSAGE_BOX_INFORMATION = 0x40
WINDOWS_MESSAGE_BOX_ERROR = 0x10


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

    def show_info(self, message: str) -> None:
        """显示不包含敏感值的连接状态消息。"""

        self._show_message(message=message, flags=WINDOWS_MESSAGE_BOX_INFORMATION)

    def show_error(self, message: str) -> None:
        """显示可操作的连接失败消息。"""

        self._show_message(message=message, flags=WINDOWS_MESSAGE_BOX_ERROR)

    def _show_message(self, *, message: str, flags: int) -> None:
        if sys.platform != "win32":
            raise OSError("Agent消息窗口只支持Windows交互会话。")
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "Codex Remote Agent",
            flags,
        )

    def select_workspace(self) -> Path:
        """使用 Windows 原生窗口选择首个允许的项目目录。"""

        if sys.platform != "win32":
            raise OSError("Agent项目目录选择只支持Windows交互会话。")
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory(
                parent=root,
                title="选择允许 Codex 使用的项目目录",
                mustexist=True,
            )
        finally:
            root.destroy()
        if not selected:
            raise PermissionError("用户取消了项目目录选择。")
        return Path(selected).resolve(strict=True)

    def select_codex_binary(self) -> str:
        """PATH 无法解析时选择已有 Codex，不安装或管理主机账号。"""
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilename(
                parent=root,
                title="选择已安装的 Codex 程序",
                filetypes=[("Codex 程序", "*.exe *.cmd *.bat"), ("所有文件", "*.*")],
            )
        finally:
            root.destroy()
        if not selected:
            raise PermissionError(
                "已取消选择 Codex 程序；安装指引：https://developers.openai.com/codex/cli"
            )
        return str(Path(selected).resolve(strict=True))


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
        self._authorization_request: DeviceAuthorizationCreateRequestEnvelope | None = None

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
        agent_version: str,
        schema_digest: str,
        codex_binary: str = "codex",
        workspace: AgentWorkspaceSettings | None,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
        development_ca_certificate_path: Path | None = None,
        enrollment_intent_token: str | None = None,
        network_settings: AgentNetworkSettings | None = None,
        default_workspace_key: str = "default",
        default_workspace_name: str = "默认工作区",
    ) -> CodexHostAgentSettings:
        attempt_store = AgentEnrollmentAttemptStore(config_path, self._acl_enforcer)
        attempt = attempt_store.read()
        resuming = attempt is not None
        if attempt is not None and attempt.api_url != api_url:
            raise ValueError("已有绑定尝试属于另一个服务，不能覆盖设备身份。")
        resolved_workspace = attempt.workspace if attempt is not None else workspace
        if resolved_workspace is None:
            selected_root = self._ui.select_workspace()
            resolved_workspace = AgentWorkspaceSettings(
                key=default_workspace_key,
                display_name=selected_root.name or default_workspace_name,
                root=selected_root,
                allow_write=True,
            )
        # 先证明配置目录可原子写入，再创建服务端身份。
        probe_path = config_path.with_name(f".enrollment-{uuid4().hex}.toml")
        try:
            AgentConfigStore(probe_path, self._acl_enforcer).write(b"# enrollment write probe\n")
        finally:
            probe_path.unlink(missing_ok=True)
        key_id = attempt.request.detail.key_id if attempt is not None else uuid4()
        public_key = (
            self._key_store.read_public_key(key_id)
            if attempt is not None
            else self._key_store.generate(key_id)
        )
        if attempt is None:
            attempt = AgentEnrollmentAttempt(
                api_url=api_url,
                created_at=datetime.now(UTC),
                workspace=resolved_workspace,
                intent_token=enrollment_intent_token,
                request=self._build_create_request(
                    key_id=key_id,
                    public_key=public_key,
                    display_name=display_name,
                    platform=platform,
                ),
            )
            attempt_store.write(attempt)
        if enrollment_intent_token is not None and enrollment_intent_token != attempt.intent_token:
            attempt = attempt.model_copy(
                update={"intent_token": enrollment_intent_token, "issued": None}
            )
            attempt_store.write(attempt)
        self._authorization_request = attempt.request
        enrollment_intent_token = attempt.intent_token
        status = None
        if resuming:
            try:
                status = await self._recover_authorization(api_url, key_id, key_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {404, 409}:
                    raise
        if status is None:
            try:
                issued = attempt.issued or (
                    await self._consume_enrollment_intent(
                        api_url=api_url,
                        intent_token=enrollment_intent_token,
                        key_id=key_id,
                        public_key=public_key,
                        display_name=display_name,
                        platform=platform,
                    )
                    if enrollment_intent_token is not None
                    else await self._create_authorization(
                        api_url=api_url,
                        key_id=key_id,
                        public_key=public_key,
                        display_name=display_name,
                        platform=platform,
                    )
                )
                attempt = attempt.model_copy(update={"issued": issued})
                attempt_store.write(attempt)
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
                # 同机 intent 由原浏览器继续批准，避免打开另一登录会话。
                # 跨设备连接只打开授权页，信息框不能阻塞授权轮询。
                if enrollment_intent_token is None:
                    webbrowser.open(resolved_verification_uri)
                status = await self._poll_until_terminal(api_url=api_url, issued=issued)
                if status.state != DeviceAuthorizationState.APPROVED or status.host_id is None:
                    if status.state in {
                        DeviceAuthorizationState.DENIED,
                        DeviceAuthorizationState.CANCELLED,
                    }:
                        attempt_store.clear()
                        self._key_store.delete(key_id)
                    raise PermissionError("设备授权未获批准。")
                if status.key_id != key_id:
                    raise PermissionError("服务端批准的设备key与本机密钥不一致。")
            except (httpx.HTTPStatusError, TimeoutError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {
                    404,
                    409,
                    410,
                }:
                    raise
                status = await self._recover_authorization(api_url, key_id, key_id)
        settings = CodexHostAgentSettings(
            agent=AgentProcessSettings(
                host_id=status.host_id,
                key_id=key_id,
                display_name=display_name,
                deployment_profile=deployment_profile,
                control_plane_url=websocket_url,
                control_plane_api_url=api_url,
                development_ca_certificate_path=development_ca_certificate_path,
                network_mode=network_settings.network_mode if network_settings else "system",
                proxy_url=network_settings.proxy_url if network_settings else None,
                ca_certificate_path=network_settings.ca_certificate_path
                if network_settings
                else None,
                codex_binary=codex_binary,
                state_database=config_path.parent / "state.sqlite",
            ),
            protocol=AgentProtocolSettings(
                agent_schema_version=CodexConnectionProtocolVersion.V2,
                agent_version=agent_version,
                expected_codex_version=expected_codex_version,
                app_server_schema_digest=schema_digest,
            ),
            workspaces=[resolved_workspace],
        )
        store = AgentConfigStore(config_path, self._acl_enforcer)
        store.write(store.serialize(settings))
        attempt_store.clear()
        return settings

    async def _recover_authorization(
        self, api_url: str, enrollment_id: UUID, key_id: UUID
    ) -> DeviceAuthorizationRecoveryResult:
        url = f"{api_url.rstrip('/')}{DEVICE_AUTHORIZATION_CREATE_PATH}/recover"
        request = DeviceAuthorizationRecoveryRequest(enrollment_id=enrollment_id, key_id=key_id)
        response = await self._client.post(url, json=request.model_dump(mode="json"))
        response.raise_for_status()
        challenge = DeviceChallengeIssue.model_validate(response.json())
        message = DeviceChallengeCanonicalMessage(**challenge.model_dump())
        proof = DeviceChallengeProof(
            challenge_id=challenge.challenge_id,
            host_id=challenge.host_id,
            key_id=key_id,
            signature_base64=base64.b64encode(
                self._key_store.sign(key_id, message.canonical_bytes())
            ).decode(),
        )
        response = await self._client.post(
            url, json=request.model_copy(update={"proof": proof}).model_dump(mode="json")
        )
        response.raise_for_status()
        return DeviceAuthorizationRecoveryResult.model_validate(response.json())

    async def _create_authorization(
        self,
        *,
        api_url: str,
        key_id: UUID,
        public_key: bytes,
        display_name: str,
        platform: str,
    ) -> DeviceAuthorizationEnvelope:
        response = await self._post_authorization(
            f"{api_url.rstrip('/')}{DEVICE_AUTHORIZATION_CREATE_PATH}",
            json=(
                self._authorization_request
                or self._build_create_request(
                    key_id=key_id,
                    public_key=public_key,
                    display_name=display_name,
                    platform=platform,
                )
            ).model_dump(mode="json"),
        )
        response.raise_for_status()
        envelope = DeviceAuthorizationEnvelope.model_validate(response.json())
        if not isinstance(envelope.detail, DeviceAuthorizationIssuedDetail):
            raise ValueError("设备授权创建未返回issued扩展。")
        return envelope

    async def _consume_enrollment_intent(
        self,
        *,
        api_url: str,
        intent_token: str,
        key_id: UUID,
        public_key: bytes,
        display_name: str,
        platform: str,
    ) -> DeviceAuthorizationEnvelope:
        response = await self._post_authorization(
            f"{api_url.rstrip('/')}{ENROLLMENT_INTENT_CONSUME_PATH}",
            json=CodexEnrollmentIntentConsumeRequestEnvelope(
                header=CodexEnrollmentIntentRequestHeader(request_id=uuid4()),
                detail=CodexEnrollmentIntentConsumeDetail(
                    intent_token=intent_token,
                    authorization=(
                        self._authorization_request
                        or self._build_create_request(
                            key_id=key_id,
                            public_key=public_key,
                            display_name=display_name,
                            platform=platform,
                        )
                    ).detail,
                ),
            ).model_dump(mode="json"),
        )
        response.raise_for_status()
        envelope = DeviceAuthorizationEnvelope.model_validate(response.json())
        if not isinstance(envelope.detail, DeviceAuthorizationIssuedDetail):
            raise ValueError("注册意图消费未返回设备授权issued扩展。")
        return envelope

    async def _post_authorization(self, url: str, *, json: dict[str, object]) -> httpx.Response:
        """只重试已经具备同 key 幂等语义的注册提交；不生成新请求身份。"""
        deadline = asyncio.get_running_loop().time() + 30
        delay = 1.0
        while True:
            try:
                response = await self._client.post(url, json=json)
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0 or not AgentControlConnectionPolicy.should_retry(exc):
                    raise
                wait = AgentControlConnectionPolicy.read_retry_after_seconds(exc) or delay
                await asyncio.sleep(min(remaining, wait))
                delay = min(delay * 2, 10)

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
        delay = float(issued.detail.interval_seconds)
        while datetime.now(UTC) < issued.detail.expires_at:
            await asyncio.sleep(
                min(delay, max(0, (issued.detail.expires_at - datetime.now(UTC)).total_seconds()))
            )
            try:
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
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 409:
                    continue
                if not AgentControlConnectionPolicy.should_retry(exc):
                    raise
                delay = max(
                    issued.detail.interval_seconds,
                    AgentControlConnectionPolicy.read_retry_after_seconds(exc)
                    or min(delay * 2, 30),
                )
                continue
            delay = float(issued.detail.interval_seconds)
            envelope = DeviceAuthorizationEnvelope.model_validate(response.json())
            if not isinstance(envelope.detail, DeviceAuthorizationStatusDetail):
                raise ValueError("设备授权轮询未返回status扩展。")
            if envelope.detail.state in {
                DeviceAuthorizationState.APPROVED,
                DeviceAuthorizationState.DENIED,
                DeviceAuthorizationState.EXPIRED,
                DeviceAuthorizationState.CANCELLED,
            }:
                if envelope.detail.state == DeviceAuthorizationState.EXPIRED:
                    raise TimeoutError("授权窗口已结束，正在核对持久批准结果。")
                return envelope.detail
        raise TimeoutError("授权窗口已结束，正在核对持久批准结果。")
