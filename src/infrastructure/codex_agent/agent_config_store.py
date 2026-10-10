"""Agent 配置唯一的原子文件提交原语，不承担进程重启。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import uuid4

import rtoml

from src.infrastructure.codex_agent.agent_configuration import CodexHostAgentSettings
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
)


class AgentConfigStore:
    """替换前完成校验、权限及刷盘；提交后没有可失败的权限操作。"""

    def __init__(self, path: Path, acl: WindowsCurrentUserAclEnforcer) -> None:
        self._path = path
        self._acl = acl

    def serialize(self, settings: CodexHostAgentSettings) -> bytes:
        validated = CodexHostAgentSettings.model_validate(settings.model_dump())
        return rtoml.dumps(validated.model_dump(mode="json", exclude_none=True)).encode("utf-8")

    def write(self, content: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._acl.enforce_config(temporary)
            if self._path.exists():
                self._acl.enforce_config(self._path)
            os.replace(temporary, self._path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logging.getLogger("codex_host_agent").warning(
                    "配置临时文件清理失败，原始提交结果不变。", exc_info=True
                )
