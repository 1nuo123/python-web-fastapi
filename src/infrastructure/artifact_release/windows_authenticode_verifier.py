"""Windows Authenticode 薄适配器。"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from src.core.artifact_release_contract.artifact_contract import (
    ArtifactReleaseEnvelope,
    ArtifactSignatureDetail,
    ArtifactVerificationResult,
)
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)

POWERSHELL_EXECUTABLE = "powershell.exe"
AUTHENTICODE_STATUS_VALID = "Valid"
SHA256_HEX_LENGTH = 64
SUBPROCESS_ERROR_TYPE = subprocess.SubprocessError


class WindowsAuthenticodeVerifier:
    """委托 Windows 签名验证工具，不复制证书链算法。"""

    def __init__(
        self,
        *,
        allowed_signer_sha256: tuple[str, ...],
        subprocess_launcher: WindowsSubprocessLauncher | None = None,
    ) -> None:
        self._allowed_signer_sha256 = tuple(value.lower() for value in allowed_signer_sha256)
        self._subprocess_launcher = subprocess_launcher or WindowsSubprocessLauncher()
        if not self._allowed_signer_sha256:
            raise ValueError("必须固定至少一个Authenticode签名证书指纹。")

    async def verify(self, path: Path) -> ArtifactSignatureDetail:
        return await asyncio.to_thread(self._verify_sync, path)

    def _verify_sync(self, path: Path) -> ArtifactSignatureDetail:
        result = self._subprocess_launcher.run(
            WindowsSubprocessRequest(
                argv=(
                    POWERSHELL_EXECUTABLE,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "$signature = Get-AuthenticodeSignature -LiteralPath $args[0]; "
                        "[ordered]@{Status=[string]$signature.Status; "
                        "Subject=[string]$signature.SignerCertificate.Subject; "
                        "SignerSha256=[string]$signature.SignerCertificate.GetCertHashString('SHA256')} "
                        "| ConvertTo-Json -Compress"
                    ),
                    str(path),
                ),
                timeout_seconds=30,
                log_category=WindowsSubprocessLogCategory.POWERSHELL,
            )
        )
        if result.return_code != 0:
            raise ValueError("Windows Authenticode签名命令执行失败。")
        payload = json.loads(result.stdout)
        if payload.get("Status") != AUTHENTICODE_STATUS_VALID:
            raise ValueError("Windows Authenticode 签名校验失败。")
        signer_sha256 = str(payload.get("SignerSha256", "")).lower()
        if (
            len(signer_sha256) != SHA256_HEX_LENGTH
            or signer_sha256 not in self._allowed_signer_sha256
        ):
            raise ValueError("Windows Authenticode签名证书不在允许列表中。")
        return ArtifactSignatureDetail(
            method="authenticode",
            signer_subject=str(payload.get("Subject", "")) or None,
            signer_sha256=signer_sha256,
            verified_at=datetime.now(UTC),
        )


class WindowsAuthenticodeArtifactVerifier:
    """把下载字节暂存到受控临时文件并执行 Authenticode 验证。"""

    def __init__(
        self,
        *,
        allowed_signer_sha256: tuple[str, ...] = (),
        verifier: WindowsAuthenticodeVerifier | None = None,
    ) -> None:
        self._verifier = verifier or WindowsAuthenticodeVerifier(
            allowed_signer_sha256=allowed_signer_sha256
        )

    async def verify(
        self,
        envelope: ArtifactReleaseEnvelope,
        content: bytes,
    ) -> ArtifactVerificationResult:
        suffix = ".msi" if envelope.identity.artifact_name.endswith("msi") else ".exe"
        path = await asyncio.to_thread(self._write_temporary_file, content, suffix)
        try:
            signature = await self._verifier.verify(path)
        finally:
            await asyncio.to_thread(path.unlink, True)
        return ArtifactVerificationResult(
            identity=envelope.identity,
            digest_verified=True,
            signature_verified=True,
            signature=signature,
        )

    def _write_temporary_file(self, content: bytes, suffix: str) -> Path:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as file:
            file.write(content)
            return Path(file.name)
