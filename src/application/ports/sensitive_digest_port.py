"""敏感标识摘要应用端口。"""

from __future__ import annotations

from typing import Protocol


class SensitiveDigestPort(Protocol):
    """向应用层暴露稳定摘要能力，不泄漏基础设施实现。"""

    def digest(self, value: str) -> str:
        """返回敏感原文的稳定不可逆摘要。"""

        ...
