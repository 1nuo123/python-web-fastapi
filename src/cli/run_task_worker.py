"""生产任务消费者命令行入口。"""

from __future__ import annotations

import signal
from threading import Event
from types import FrameType

from src.api.asgi_entry import create_app
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping

TASK_WORKER_EXIT_SUCCESS = 0
TASK_WORKER_SETTINGS_OVERRIDES: SettingsOverrideMapping = {
    "runtime": {"task": {"worker_enabled": True}}
}


class TaskWorkerCli:
    """装配生产处理器并持续运行 Funboost 消费者。"""

    def __init__(self) -> None:
        """初始化停止事件。"""

        self._stop_event = Event()

    def run(self) -> int:
        """启动消费者并在退出信号后释放全部资源。

        :returns: 进程退出码。
        :rtype: int
        """

        signal.signal(signal.SIGTERM, self._request_shutdown)
        signal.signal(signal.SIGINT, self._request_shutdown)
        app = create_app(
            environment=AppEnvironment.PRODUCTION,
            settings_overrides=TASK_WORKER_SETTINGS_OVERRIDES,
        )
        resource_mount = app.state.container.resource_mount
        resource_mount.startup()
        try:
            self._stop_event.wait()
        finally:
            resource_mount.shutdown()
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


if __name__ == "__main__":
    raise SystemExit(TaskWorkerCli().run())
