"""Codex command 到通用 AEAD envelope 的薄适配器。"""

from __future__ import annotations

from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.command_outbox_contract import (
    CODEX_COMMAND_CIPHER_PURPOSE,
    CODEX_COMMAND_KEY_FAMILY,
)
from src.core.cryptography_contract.aead_envelope_contract import (
    AeadContextItem,
    AeadDecryptionRequest,
    AeadEncryptionRequest,
    AeadEnvelope,
    AeadEnvelopeCipherPort,
)


class CodexCommandPayloadCipherAdapter(CodexCommandPayloadCipherPort):
    """完整绑定命令 ID、owner、host 与 request digest。"""

    def __init__(self, cipher: AeadEnvelopeCipherPort) -> None:
        self._cipher = cipher

    def encrypt(self, command: CodexAgentCommand, owner_subject_id: str) -> AeadEnvelope:
        return self._cipher.encrypt(
            AeadEncryptionRequest(
                key_family=CODEX_COMMAND_KEY_FAMILY,
                purpose=CODEX_COMMAND_CIPHER_PURPOSE,
                context=self._context(command, owner_subject_id),
                plaintext=command.model_dump_json().encode(),
            )
        )

    def decrypt(
        self,
        envelope: AeadEnvelope,
        command_reference: CodexAgentCommand,
        owner_subject_id: str,
    ) -> CodexAgentCommand:
        """使用数据库事实源 owner 重建 AAD 并解密。"""

        plaintext = self._cipher.decrypt(
            AeadDecryptionRequest(
                key_family=CODEX_COMMAND_KEY_FAMILY,
                purpose=CODEX_COMMAND_CIPHER_PURPOSE,
                context=self._context(command_reference, owner_subject_id),
                envelope=envelope,
            )
        )
        restored = CodexAgentCommand.model_validate_json(plaintext)
        if (
            restored.command_id != command_reference.command_id
            or restored.operation_id != command_reference.operation_id
            or restored.host_id != command_reference.host_id
        ):
            raise ValueError("解密命令与 outbox 稳定标识不一致。")
        return restored

    def _context(
        self,
        command: CodexAgentCommand,
        owner_subject_id: str,
    ) -> tuple[AeadContextItem, ...]:
        return (
            AeadContextItem(name="operation_id", value=str(command.operation_id)),
            AeadContextItem(name="command_id", value=str(command.command_id)),
            AeadContextItem(name="host_id", value=str(command.host_id)),
            AeadContextItem(name="owner_subject_id", value=owner_subject_id),
            AeadContextItem(name="request_digest", value=command.request_digest),
        )
