"""
配置快照存储基础设施模块。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from src.infrastructure.settings.application_settings import ApplicationSettings


@dataclass(slots=True)
class SettingsStateHolder:
    """
    配置数据对象，用于承载当前流程的结构化字段。

    :ivar current_settings: ``current_settings`` 字段。约束：需符合 ``ApplicationSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype current_settings: ApplicationSettings
    """

    current_settings: ApplicationSettings


@dataclass(slots=True)
class SettingsSnapshot:
    """
    配置数据对象，用于承载当前流程的结构化字段。

    :ivar version_id: ``version_id`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype version_id: str
    :ivar digest: 配置摘要。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype digest: str
    :ivar settings: ``settings`` 字段。约束：需符合 ``ApplicationSettings`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype settings: ApplicationSettings
    """

    version_id: str
    digest: str
    settings: ApplicationSettings


class SettingsSnapshotStore:
    """
    配置快照存储实现，负责保存和读取状态。
    """

    def __init__(self) -> None:
        """
        初始化配置快照存储。

        :returns: 无返回值。
        :rtype: None
        """

        self._latest_snapshot: SettingsSnapshot | None = None
        self._lock: threading.RLock = threading.RLock()

    def save(self, snapshot: SettingsSnapshot) -> None:
        """
        处理保存。

        :param snapshot: 历史快照对象。约束：需符合 ``SettingsSnapshot`` 注解。
        :type snapshot: SettingsSnapshot
        :returns: 无返回值。
        :rtype: None
        """

        with self._lock:
            self._latest_snapshot = SettingsSnapshot(
                version_id=snapshot.version_id,
                digest=snapshot.digest,
                settings=snapshot.settings.model_copy(deep=True),
            )

    def load_latest(self) -> SettingsSnapshot | None:
        """
        加载最新。

        :returns: 返回当前操作结果。
        :rtype: SettingsSnapshot | None
        """

        with self._lock:
            if self._latest_snapshot is None:
                return None
            return SettingsSnapshot(
                version_id=self._latest_snapshot.version_id,
                digest=self._latest_snapshot.digest,
                settings=self._latest_snapshot.settings.model_copy(deep=True),
            )
