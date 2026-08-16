"""Windows Agent Credential Manager 适配单元测试。"""

from __future__ import annotations

import keyring
import pytest
from keyring.errors import PasswordDeleteError

from src.infrastructure.codex_agent.agent_secret_store import (
    AGENT_CREDENTIAL_SERVICE_NAME,
    AgentSecretNotFoundError,
    WindowsAgentSecretStore,
)


class MemoryKeyringBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_secret_store_when_write_read_delete_should_keep_token_out_of_config() -> None:
    backend = MemoryKeyringBackend()
    store = WindowsAgentSecretStore(backend)

    store.write("credential-1", "device-token")
    assert backend.values[(AGENT_CREDENTIAL_SERVICE_NAME, "credential-1")] == "device-token"
    assert store.read("credential-1") == "device-token"
    store.delete("credential-1")

    with pytest.raises(AgentSecretNotFoundError):
        store.read("credential-1")


def test_secret_store_when_system_credential_missing_should_keep_delete_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        keyring,
        "delete_password",
        lambda _service, _username: (_ for _ in ()).throw(PasswordDeleteError()),
    )

    WindowsAgentSecretStore().delete("missing-credential")
