"""
nb_log 配置覆盖文件。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.logging_contract.log_runtime_contract import (
    LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
)

NB_LOG_CONFIG_SCHEMA_VERSION = "1.0"
NB_LOG_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE = LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE
NB_LOG_DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs"
NB_LOG_LOG_PATH_MINIMUM_LENGTH = 1


class NbLogEntrySettings(BaseModel):
    """
    nb_log 第三方入口强类型配置。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[NB_LOG_CONFIG_SCHEMA_VERSION] = NB_LOG_CONFIG_SCHEMA_VERSION
    log_path: str = Field(
        default=os.getenv(
            NB_LOG_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
            str(NB_LOG_DEFAULT_LOG_PATH),
        ),
        min_length=NB_LOG_LOG_PATH_MINIMUM_LENGTH,
    )


NB_LOG_RAW_LOG_PATH = NbLogEntrySettings().log_path
NB_LOG_RESOLVED_LOG_PATH = (
    NB_LOG_DEFAULT_LOG_PATH
    if NB_LOG_RAW_LOG_PATH == str(NB_LOG_DEFAULT_LOG_PATH)
    else Path(NB_LOG_RAW_LOG_PATH).expanduser()
)
NB_LOG_ABSOLUTE_LOG_PATH = (
    NB_LOG_RESOLVED_LOG_PATH
    if NB_LOG_RESOLVED_LOG_PATH.is_absolute()
    else Path(__file__).resolve().parent / NB_LOG_RESOLVED_LOG_PATH
)
SHOW_IMPORT_NB_LOG_CONFIG_PATH = False
LOG_PATH = str(NB_LOG_ABSOLUTE_LOG_PATH.resolve())
DEFAULUT_USE_COLOR_HANDLER = False
DISPLAY_BACKGROUD_COLOR_IN_CONSOLE = False
AUTO_PATCH_PRINT = False
SHOW_PYCHARM_COLOR_SETINGS = False
SHOW_NB_LOG_LOGO = False
AUTO_WRITE_ERROR_LEVEL_TO_SEPARATE_FILE = False
DEFAULT_ADD_MULTIPROCESSING_SAFE_ROATING_FILE_HANDLER = False
