"""
funboost 配置覆盖文件。
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from funboost.funboost_config_deafult import BrokerConnConfig as DefaultBrokerConnConfig
from funboost.funboost_config_deafult import FunboostCommonConfig as DefaultFunboostCommonConfig
from src.core.logging_contract.log_runtime_contract import (
    LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
)

FUNBOOST_CONFIG_SCHEMA_VERSION = "1.0"
FUNBOOST_PROJECT_NAME = "fastapi_web_skeleton"
FUNBOOST_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE = (
    LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE
)
FUNBOOST_PROJECT_NAME_MINIMUM_LENGTH = 1


class FunboostEntrySettings(BaseModel):
    """
    funboost 第三方入口强类型配置。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[FUNBOOST_CONFIG_SCHEMA_VERSION] = FUNBOOST_CONFIG_SCHEMA_VERSION
    project_name: str = Field(
        default=os.getenv(
            FUNBOOST_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
            FUNBOOST_PROJECT_NAME,
        ),
        min_length=FUNBOOST_PROJECT_NAME_MINIMUM_LENGTH,
    )


class BrokerConnConfig(DefaultBrokerConnConfig):
    """
    funboost 连接配置覆盖。
    """


class FunboostCommonConfig(DefaultFunboostCommonConfig):
    """
    funboost 公共配置覆盖。
    """

    PROJECT_NAME = FunboostEntrySettings().project_name
