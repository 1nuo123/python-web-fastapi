"""
Web 模块注册边界单元测试。
"""

from __future__ import annotations

import subprocess

API_PATH = "src/api"
PROVIDER_REGISTRY_PATTERN = "register_provider_type"
RIPGREP_NO_MATCH_RETURN_CODE = 1


class TestWebModuleRegistryBoundaryUnit:
    """
    Web 模块注册边界单元测试集合。
    """

    def test_api_layer_should_not_keep_provider_registry_decorator(self) -> None:
        """
        验证 API 层不应保留 provider 装饰器注册入口。
        """

        result = subprocess.run(
            [
                "rg",
                PROVIDER_REGISTRY_PATTERN,
                API_PATH,
                "-S",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == RIPGREP_NO_MATCH_RETURN_CODE, result.stdout
