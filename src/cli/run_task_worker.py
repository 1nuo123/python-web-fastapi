"""生产任务消费者命令行入口。"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from threading import Event
from types import FrameType
from typing import TYPE_CHECKING

from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.infrastructure.persistence.database_engine_factory_contract import (
        DatabaseEngineFactory,
    )
    from src.infrastructure.shared_resource_mount import SharedResourceMount
    from src.infrastructure.task.task_registration_registry import BaseModelTaskBinding

TASK_WORKER_EXIT_SUCCESS = 0
TASK_WORKER_SETTINGS_OVERRIDES: SettingsOverrideMapping = {
    "runtime": {"task": {"worker_enabled": True}}
}
TASK_WORKER_HEALTH_FILE = "TASK_WORKER_HEALTH_FILE"
TASK_WORKER_HEALTH_MAX_AGE_SECONDS = 90


def create_app(
    *,
    environment: AppEnvironment | None = None,
    config_root: str | Path = "config",
    settings_overrides: SettingsOverrideMapping | None = None,
    task_bindings: list[BaseModelTaskBinding] | None = None,
    database_engine_factory: DatabaseEngineFactory | None = None,
) -> FastAPI:
    """Lazily resolve the ASGI factory so health checks stay dependency-light."""

    from src.api.asgi_entry import create_app as application_factory

    return application_factory(
        environment=environment,
        config_root=config_root,
        settings_overrides=settings_overrides,
        task_bindings=task_bindings,
        database_engine_factory=database_engine_factory,
    )


class TaskWorkerCli:
    """装配生产处理器并持续运行 Funboost 消费者。"""

    def __init__(self) -> None:
        """初始化停止事件。"""

        self._stop_event = Event()
        self._health_written = False

    def run(self) -> int:
        """启动消费者并在退出信号后释放全部资源。

        :returns: 进程退出码。
        :rtype: int
        """

        signal.signal(signal.SIGTERM, self._request_shutdown)
        signal.signal(signal.SIGINT, self._request_shutdown)
        if len(sys.argv) > 1 and sys.argv[1] == "--healthcheck":
            return self._healthcheck()
        app = create_app(
            environment=AppEnvironment.PRODUCTION,
            settings_overrides=TASK_WORKER_SETTINGS_OVERRIDES,
        )
        resource_mount = app.state.container.resource_mount
        try:
            resource_mount.startup()
            if not self._stop_event.is_set():
                self._refresh_health(resource_mount)
            while not self._stop_event.wait(30):
                self._refresh_health(resource_mount)
        finally:
            try:
                if self._health_written:
                    self._write_health("stopping")
            finally:
                try:
                    resource_mount.shutdown()
                finally:
                    self._remove_health()
        return TASK_WORKER_EXIT_SUCCESS

    def _request_shutdown(self, signal_number: int, frame: FrameType | None) -> None:
        """接收进程退出信号并解除阻塞。

        :param signal_number: 操作系统信号编号。
        :param frame: 当前解释器栈帧。
        :returns: 无返回值。
        :rtype: None
        """

        _ = signal_number, frame
        self._stop_event.set()

    def _health_path(self) -> str:
        return os.environ.get(TASK_WORKER_HEALTH_FILE, "/tmp/task-worker-health.json")

    def _write_health(self, status: str, details: dict[str, object] | None = None) -> None:
        path = self._health_path()
        payload = {
            "status": status,
            "pid": os.getpid(),
            "updated_at": time.time(),
            "details": details or {},
        }
        temporary = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(temporary, path)
            self._health_written = True
        except OSError:
            raise

    def _refresh_health(self, resource_mount: SharedResourceMount) -> None:
        dispatcher = resource_mount.get_task_dispatcher()
        checker = getattr(dispatcher, "health_check", None)
        if not callable(checker):
            self._write_health("not_ready", {"reason": "runtime_health_unavailable"})
            return
        ready, details = checker()
        if not ready:
            recover = getattr(dispatcher, "recover_consumers", None)
            if callable(recover):
                try:
                    recover()
                except Exception as exc:
                    details = {**details, "recovery_error": type(exc).__name__}
                else:
                    ready, details = checker()
        self._write_health("ready" if ready else "not_ready", details)

    def _remove_health(self) -> None:
        try:
            os.unlink(self._health_path())
        except FileNotFoundError:
            pass

    def _healthcheck(self) -> int:
        try:
            with open(self._health_path(), encoding="utf-8") as handle:
                payload = json.load(handle)
            fresh = time.time() - float(payload["updated_at"]) <= TASK_WORKER_HEALTH_MAX_AGE_SECONDS
            details = payload.get("details")
            detail_ready = isinstance(details, dict) and all(
                details.get(key) is True
                for key in ("broker_ready", "consumer_ready", "binding_ready")
            )
            return 0 if payload.get("status") == "ready" and detail_ready and fresh else 1
        except (OSError, ValueError, KeyError, TypeError):
            return 1


if __name__ == "__main__":
    raise SystemExit(TaskWorkerCli().run())
