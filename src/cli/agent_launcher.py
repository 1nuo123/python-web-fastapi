"""稳定启动器：只运行已激活且由 active-version.json 选择的版本。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from loguru import logger

ACTIVE_VERSION_FILE_NAME = "active-version.json"
LAUNCH_EXECUTABLE_NAME = "codex-remote-agent.exe"


class CodexAgentLauncher:
    """校验版本目录 containment 后启动 Agent。"""

    def __init__(self, *, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def run(self) -> int:
        active_file = self._root / ACTIVE_VERSION_FILE_NAME
        payload = json.loads(active_file.read_text("utf-8"))
        configured_path = Path(str(payload["path"])).resolve()
        if self._root not in configured_path.parents:
            raise ValueError("激活版本目录超出 Agent managed root。")
        executable = configured_path.parent / LAUNCH_EXECUTABLE_NAME
        if not executable.is_file():
            raise FileNotFoundError("激活版本缺少 Agent 启动文件。")
        logger.info("启动已激活的 Codex Agent 版本。")
        return subprocess.run([str(executable)], check=False).returncode
