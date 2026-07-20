"""
第三方日志入口环境桥接模块。
"""

from __future__ import annotations

import importlib
import os
import sys
from types import ModuleType

from src.core.logging_contract.log_runtime_contract import (
    LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
    LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
    LoggingRuntimeSettings,
)

THIRD_PARTY_ENTRY_MODULE_NAMES: tuple[str, ...] = ("funboost_config", "nb_log_config")


class LoggingEntryEnvironmentBridge:
    """
    第三方日志入口环境桥接器。
    """

    def apply(self, settings: LoggingRuntimeSettings) -> None:
        """
        将强类型日志运行时配置桥接到第三方入口环境变量。

        :param settings: 已校验的日志运行时配置。
        :type settings: LoggingRuntimeSettings
        :returns: 无返回值。
        :rtype: None
        """

        os.environ[LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE] = settings.entry_project_name
        os.environ[LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE] = settings.entry_log_path
        self._reload_loaded_entry_modules()

    def _reload_loaded_entry_modules(self) -> None:
        """
        重载已经导入的第三方入口配置模块。

        :returns: 无返回值。
        :rtype: None
        """

        for module_name in THIRD_PARTY_ENTRY_MODULE_NAMES:
            module = sys.modules.get(module_name)
            if isinstance(module, ModuleType):
                importlib.reload(module)
