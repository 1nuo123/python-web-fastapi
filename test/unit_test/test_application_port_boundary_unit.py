"""
应用层端口边界单元测试。
"""

from __future__ import annotations

import subprocess

APPLICATION_PATH = "src/application"
INFRASTRUCTURE_IMPORT_PATTERN = "from src\\.infrastructure"


class TestApplicationPortBoundaryUnit:
    """
    应用层端口边界单元测试集合。
    """

    def test_application_layer_should_not_import_infrastructure(self) -> None:
        """
        验证应用层不应直接依赖基础设施实现。
        """

        result = subprocess.run(
            [
                "rg",
                INFRASTRUCTURE_IMPORT_PATTERN,
                APPLICATION_PATH,
                "-g",
                "*.py",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1, result.stdout
