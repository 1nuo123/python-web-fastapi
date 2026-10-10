"""Windows current-user DPAPI 设备私钥存储。"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import POINTER, Structure, c_ubyte, c_uint32, c_void_p
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from src.application.ports.agent_device_key_store_port import AgentDeviceKeyStorePort
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)

DPAPI_ENTROPY = b"CodexRemoteAgent.current-user.device-key.v1"
PRIVATE_KEY_LENGTH = 32
POWERSHELL_ACL_EXECUTABLE = "icacls.exe"
CURRENT_USER_COMMAND = "whoami.exe"
SUBPROCESS_ERROR_TYPE = subprocess.SubprocessError


class _DataBlob(Structure):
    _fields_ = [("cbData", c_uint32), ("pbData", POINTER(c_ubyte))]


class WindowsCurrentUserDpapi:
    """CryptProtectData/CryptUnprotectData 的窄 ctypes 适配器。"""

    def protect(self, value: bytes) -> bytes:
        return self._call(value, protect=True)

    def unprotect(self, value: bytes) -> bytes:
        return self._call(value, protect=False)

    def _call(self, value: bytes, *, protect: bool) -> bytes:
        if sys.platform != "win32":
            raise OSError("DPAPI设备密钥存储只能在Windows当前用户会话中运行。")
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        input_buffer = (c_ubyte * len(value)).from_buffer_copy(value)
        entropy_buffer = (c_ubyte * len(DPAPI_ENTROPY)).from_buffer_copy(DPAPI_ENTROPY)
        input_blob = _DataBlob(len(value), input_buffer)
        entropy_blob = _DataBlob(len(DPAPI_ENTROPY), entropy_buffer)
        output_blob = _DataBlob()
        function_name = "CryptProtectData" if protect else "CryptUnprotectData"
        function = getattr(crypt32, function_name)
        function.restype = ctypes.c_bool
        function.argtypes = [
            POINTER(_DataBlob),
            ctypes.c_wchar_p,
            POINTER(_DataBlob),
            c_void_p,
            c_void_p,
            c_uint32,
            POINTER(_DataBlob),
        ]
        success = function(
            ctypes.byref(input_blob),
            "Codex Remote Agent device key",
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
        if not success:
            raise OSError(ctypes.get_last_error(), "DPAPI设备密钥操作失败。")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)


class WindowsCurrentUserAclEnforcer:
    """将密钥文件 ACL 收敛到当前 Windows 用户。"""

    def __init__(self, subprocess_launcher: WindowsSubprocessLauncher | None = None) -> None:
        self._subprocess_launcher = subprocess_launcher or WindowsSubprocessLauncher()

    def enforce(self, path: Path) -> None:
        """当前用户拥有密钥的读写与删除权，以支持撤销和轮换收尾。"""

        self._enforce(path, rights="R,W,D")

    def enforce_config(self, path: Path) -> None:
        """配置允许当前用户原子替换及删除；密钥权限保持独立。"""

        self._enforce(path, rights="M")

    def _enforce(self, path: Path, *, rights: str) -> None:
        if sys.platform != "win32":
            raise OSError("设备密钥 ACL 只能在Windows中设置。")
        identity_result = self._subprocess_launcher.run(
            WindowsSubprocessRequest(
                argv=(CURRENT_USER_COMMAND, "/user", "/fo", "csv", "/nh"),
                timeout_seconds=10,
                log_category=WindowsSubprocessLogCategory.WINDOWS,
            )
        )
        if identity_result.return_code != 0:
            raise OSError("无法读取当前用户 SID。")
        identity = identity_result.stdout.strip().strip('"').split('","')
        if len(identity) < 2 or not identity[1]:
            raise OSError("无法解析当前用户 SID。")
        acl_result = self._subprocess_launcher.run(
            WindowsSubprocessRequest(
                argv=(
                    POWERSHELL_ACL_EXECUTABLE,
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"*{identity[1]}:({rights})",
                ),
                timeout_seconds=10,
                log_category=WindowsSubprocessLogCategory.WINDOWS,
            )
        )
        if acl_result.return_code != 0:
            raise OSError("设备密钥 ACL 收敛失败。")


class WindowsDpapiDeviceKeyStore(AgentDeviceKeyStorePort):
    """Ed25519 raw 私钥经 current-user DPAPI 保护后落盘。"""

    def __init__(
        self,
        *,
        root: str | Path,
        dpapi: WindowsCurrentUserDpapi | None = None,
        acl_enforcer: WindowsCurrentUserAclEnforcer | None = None,
    ) -> None:
        self._root = Path(root)
        self._dpapi = dpapi or WindowsCurrentUserDpapi()
        self._acl_enforcer = acl_enforcer or WindowsCurrentUserAclEnforcer()

    def generate(self, key_id: UUID) -> bytes:
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            Encoding.Raw,
            PrivateFormat.Raw,
            NoEncryption(),
        )
        path = self._path(key_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._dpapi.protect(private_bytes))
        self._acl_enforcer.enforce(path)
        return private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def read_public_key(self, key_id: UUID) -> bytes:
        return (
            Ed25519PrivateKey.from_private_bytes(self._read_private(key_id))
            .public_key()
            .public_bytes(
                Encoding.Raw,
                format=PublicFormat.Raw,
            )
        )

    def sign(self, key_id: UUID, message: bytes) -> bytes:
        return Ed25519PrivateKey.from_private_bytes(self._read_private(key_id)).sign(message)

    def delete(self, key_id: UUID) -> None:
        path = self._path(key_id)
        if not path.exists():
            return
        # 旧版本只授予 R,W；统一在密钥存储边界修复其删除权限。
        self._acl_enforcer.enforce(path)
        path.unlink(missing_ok=True)

    def _read_private(self, key_id: UUID) -> bytes:
        private_bytes = self._dpapi.unprotect(self._path(key_id).read_bytes())
        if len(private_bytes) != PRIVATE_KEY_LENGTH:
            raise ValueError("DPAPI设备私钥长度无效。")
        return private_bytes

    def _path(self, key_id: UUID) -> Path:
        return self._root / f"{key_id}.dpapi"
