"""首次绑定的最小恢复记录，与配置共用原子落盘和 current-user DPAPI。"""

from pathlib import Path
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateRequestEnvelope,
    DeviceAuthorizationEnvelope,
)
from src.infrastructure.codex_agent.agent_configuration import AgentWorkspaceSettings
from src.infrastructure.codex_agent.agent_config_store import AgentConfigStore
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserDpapi,
    WindowsCurrentUserAclEnforcer,
)


class AgentEnrollmentAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    api_url: str
    created_at: datetime
    workspace: AgentWorkspaceSettings
    request: DeviceAuthorizationCreateRequestEnvelope
    intent_token: str | None = None
    issued: DeviceAuthorizationEnvelope | None = None


class AgentEnrollmentAttemptStore:
    def __init__(self, config_path: Path, acl: WindowsCurrentUserAclEnforcer) -> None:
        self._path = config_path.with_name("enrollment.dpapi")
        self._atomic = AgentConfigStore(self._path, acl)
        self._dpapi = WindowsCurrentUserDpapi()

    def read(self) -> AgentEnrollmentAttempt | None:
        if not self._path.exists():
            return None
        return AgentEnrollmentAttempt.model_validate_json(
            self._dpapi.unprotect(self._path.read_bytes())
        )

    def write(self, attempt: AgentEnrollmentAttempt) -> None:
        self._atomic.write(self._dpapi.protect(attempt.model_dump_json().encode()))

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
