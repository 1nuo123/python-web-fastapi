"""从应用配置启动 Uvicorn Web Server。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import uvicorn

from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.infrastructure.settings.application_settings import ApplicationSettings
from src.infrastructure.logging.web_server_logging import build_web_server_log_config
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader

ASGI_APPLICATION_FACTORY: Final = "src.api.asgi_entry:create_app"
WEB_SERVER_HOST: Final = "0.0.0.0"  # nosec B104 - 容器入口必须监听全部网络接口。
WEB_SERVER_PORT: Final = 8000
WEB_SERVER_GRACEFUL_SHUTDOWN_BUFFER_SECONDS: Final = 5
WEB_SERVER_DISABLED_WEBSOCKET_SAFE_MAX_MESSAGE_BYTES: Final = 65_536


@dataclass(frozen=True, slots=True)
class WebServerRuntimeProjection:
    """流运行时到 Uvicorn 启动参数的强类型投影。"""

    websocket_max_message_bytes: int
    websocket_ping_interval_seconds: float
    websocket_ping_timeout_seconds: float
    graceful_shutdown_seconds: int

    @classmethod
    def from_runtime_settings(
        cls,
        settings: ApplicationSettings,
    ) -> WebServerRuntimeProjection:
        """构建并校验服务器停机窗口投影。"""

        detail = settings.runtime.stream.detail
        limits: list[int] = []
        if settings.runtime.stream.header.enabled:
            limits.append(detail.websocket_max_message_bytes)
        codex = settings.runtime.codex_control
        enabled = settings.app.modules.enabled
        if codex.enabled:
            if ApplicationModuleName.CODEX_AGENT_GATEWAY in enabled:
                limits.append(codex.max_agent_frame_bytes)
            if ApplicationModuleName.CODEX_CONTROL in enabled:
                limits.append(codex.max_browser_frame_bytes)
        graceful_shutdown_seconds = (
            int(detail.shutdown_grace_seconds) + WEB_SERVER_GRACEFUL_SHUTDOWN_BUFFER_SECONDS
        )
        if graceful_shutdown_seconds <= detail.shutdown_grace_seconds:
            raise ValueError("Uvicorn 优雅停机窗口必须大于应用流排空窗口。")
        return cls(
            websocket_max_message_bytes=max(
                limits, default=WEB_SERVER_DISABLED_WEBSOCKET_SAFE_MAX_MESSAGE_BYTES
            ),
            websocket_ping_interval_seconds=detail.websocket_ping_interval_seconds,
            websocket_ping_timeout_seconds=detail.websocket_ping_timeout_seconds,
            graceful_shutdown_seconds=graceful_shutdown_seconds,
        )


class WebServerRunner:
    """把流式运行时限制投影为 Uvicorn 启动参数。"""

    def run(self) -> None:
        """加载配置并启动 Uvicorn。

        :returns: 无返回值。
        :rtype: None
        """

        settings = AppSettingsLoader().load()
        projection = WebServerRuntimeProjection.from_runtime_settings(settings)
        uvicorn.run(
            ASGI_APPLICATION_FACTORY,
            factory=True,
            host=WEB_SERVER_HOST,
            port=WEB_SERVER_PORT,
            ws="websockets",
            ws_max_size=projection.websocket_max_message_bytes,
            ws_ping_interval=projection.websocket_ping_interval_seconds,
            ws_ping_timeout=projection.websocket_ping_timeout_seconds,
            timeout_graceful_shutdown=projection.graceful_shutdown_seconds,
            log_config=build_web_server_log_config(),
        )


if __name__ == "__main__":
    WebServerRunner().run()
