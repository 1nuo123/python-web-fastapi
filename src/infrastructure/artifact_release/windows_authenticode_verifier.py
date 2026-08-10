"""Windows Authenticode 薄适配器。"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from src.core.artifact_release_contract.artifact_contract import ArtifactSignatureDetail

POWERSHELL_EXECUTABLE = "powershell.exe"
AUTHENTICODE_STATUS_VALID = "Valid"


class WindowsAuthenticodeVerifier:
    """委托 Windows 签名验证工具，不复制证书链算法。"""

    async def verify(self, path: Path) -> ArtifactSignatureDetail:
        return await asyncio.to_thread(self._verify_sync, path)

    def _verify_sync(self, path: Path) -> ArtifactSignatureDetail:
        result = subprocess.run(
            [
                POWERSHELL_EXECUTABLE,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip() != AUTHENTICODE_STATUS_VALID:
            raise ValueError("Windows Authenticode 签名校验失败。")
        return ArtifactSignatureDetail(
            method="authenticode",
            verified_at=datetime.now(UTC),
        )
