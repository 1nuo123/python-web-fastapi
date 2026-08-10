"""Codex command payload 加密端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.cryptography_contract.aead_envelope_contract import AeadEnvelope


class CodexCommandPayloadCipherPort(Protocol):
    """完整绑定命令稳定标识的加解密端口。"""

    def encrypt(self, command: CodexAgentCommand, owner_subject_id: str) -> AeadEnvelope: ...

    def decrypt(
        self,
        envelope: AeadEnvelope,
        command_reference: CodexAgentCommand,
        owner_subject_id: str,
    ) -> CodexAgentCommand: ...
