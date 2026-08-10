"""应用生命周期内延迟解析敏感摘要服务。"""

from __future__ import annotations

from collections.abc import Callable

from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)


class DeferredSensitiveDigestService(SensitiveDigestService):
    """让装配期业务适配器在请求时访问已启动的摘要服务。"""

    def __init__(self, *, service_provider: Callable[[], SensitiveDigestService]) -> None:
        self._service_provider = service_provider

    def digest(self, value: str) -> str:
        return self._service_provider().digest(value)
