"""
本地 dotenv 配置来源加载器。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DOTENV_SOURCE_SCHEMA_VERSION: Final = "1.0"
PROCESS_ENVIRONMENT_SOURCE_KIND: Final = "process_environment"
DOTENV_FILE_SOURCE_KIND: Final = "dotenv_file"
LOCAL_STARTUP_POLICY_KIND: Final = "local_startup_policy"
DOTENV_SEPARATOR = "="
DOTENV_COMMENT_PREFIX = "#"
DOTENV_DOUBLE_QUOTE = '"'
DOTENV_SINGLE_QUOTE = "'"
SOURCE_NAME_PROCESS_ENVIRONMENT = "process_environment"
SOURCE_NAME_LOCAL_DOTENV = "local_dotenv"


@dataclass(slots=True)
class DotenvSettingsLoadResult:
    """
    dotenv 读取结果。

    :ivar variables: 从 dotenv 文件中解析出的环境变量映射。
    :vartype variables: dict[str, str]
    :ivar source_envelope: 本次读取对应的配置来源信封。
    :vartype source_envelope: SettingsSourceEnvelope
    """

    variables: dict[str, str]
    source_envelope: SettingsSourceEnvelope


class SettingsSourceHeader(BaseModel):
    """
    配置来源公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["process_environment", "dotenv_file"]
    schema_version: Literal["1.0"] = DOTENV_SOURCE_SCHEMA_VERSION
    environment: str
    source_name: str


class ProcessEnvironmentSourceDetail(BaseModel):
    """
    进程环境变量来源扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["process_environment"] = PROCESS_ENVIRONMENT_SOURCE_KIND
    schema_version: Literal["1.0"] = DOTENV_SOURCE_SCHEMA_VERSION
    enabled: bool


class DotenvSourceDetail(BaseModel):
    """
    本地 dotenv 来源扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["dotenv_file"] = DOTENV_FILE_SOURCE_KIND
    schema_version: Literal["1.0"] = DOTENV_SOURCE_SCHEMA_VERSION
    dotenv_path: str
    enabled: bool
    existing: bool


SettingsSourceDetail = Annotated[
    ProcessEnvironmentSourceDetail | DotenvSourceDetail,
    Field(discriminator="kind"),
]


class SettingsSourceEnvelope(BaseModel):
    """
    配置来源信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: SettingsSourceHeader
    detail: SettingsSourceDetail

    @model_validator(mode="after")
    def validate_source_contract(self) -> SettingsSourceEnvelope:
        """
        校验配置来源公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("配置来源 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("配置来源 header.schema_version 必须与 detail.schema_version 一致。")
        return self


class LocalStartupPolicy(BaseModel):
    """
    本地启动策略。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["local_startup_policy"] = LOCAL_STARTUP_POLICY_KIND
    schema_version: Literal["1.0"] = DOTENV_SOURCE_SCHEMA_VERSION
    environment: str
    dotenv_enabled: bool


class DotenvSettingsLoader:
    """
    本地 dotenv 配置来源加载器。
    """

    def load(
        self, *, dotenv_path: Path, environment: str, enabled: bool
    ) -> DotenvSettingsLoadResult:
        """
        读取 dotenv 文件。

        :param dotenv_path: dotenv 文件路径。
        :type dotenv_path: Path
        :param environment: 当前运行环境名称。
        :type environment: str
        :param enabled: 当前环境是否允许读取 dotenv。
        :type enabled: bool
        :returns: dotenv 读取结果。
        :rtype: DotenvSettingsLoadResult
        """

        existing = dotenv_path.exists()
        variables = (
            self._parse_dotenv_content(dotenv_path.read_text(encoding="utf-8"))
            if enabled and existing
            else {}
        )
        return DotenvSettingsLoadResult(
            variables=variables,
            source_envelope=SettingsSourceEnvelope(
                header=SettingsSourceHeader(
                    kind=DOTENV_FILE_SOURCE_KIND,
                    environment=environment,
                    source_name=SOURCE_NAME_LOCAL_DOTENV,
                ),
                detail=DotenvSourceDetail(
                    dotenv_path=str(dotenv_path),
                    enabled=enabled,
                    existing=existing,
                ),
            ),
        )

    def build_process_source_envelope(self, *, environment: str) -> SettingsSourceEnvelope:
        """
        构建进程环境变量来源信封。

        :param environment: 当前运行环境名称。
        :type environment: str
        :returns: 进程环境变量来源信封。
        :rtype: SettingsSourceEnvelope
        """

        return SettingsSourceEnvelope(
            header=SettingsSourceHeader(
                kind=PROCESS_ENVIRONMENT_SOURCE_KIND,
                environment=environment,
                source_name=SOURCE_NAME_PROCESS_ENVIRONMENT,
            ),
            detail=ProcessEnvironmentSourceDetail(enabled=True),
        )

    def build_local_startup_policy(
        self,
        *,
        environment: str,
        dotenv_enabled: bool,
    ) -> LocalStartupPolicy:
        """
        构建本地启动策略。

        :param environment: 当前运行环境名称。
        :type environment: str
        :param dotenv_enabled: 当前环境是否允许读取 dotenv。
        :type dotenv_enabled: bool
        :returns: 本地启动策略。
        :rtype: LocalStartupPolicy
        """

        return LocalStartupPolicy(
            environment=environment,
            dotenv_enabled=dotenv_enabled,
        )

    def _parse_dotenv_content(self, content: str) -> dict[str, str]:
        """
        解析 dotenv 文本。

        :param content: dotenv 原始文本。
        :type content: str
        :returns: 变量名到变量值的映射。
        :rtype: dict[str, str]
        :raises ValueError: 当行格式不符合简单 ``KEY=VALUE`` 约束时抛出。
        """

        variables: dict[str, str] = {}
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            stripped_line = raw_line.strip()
            if stripped_line == "" or stripped_line.startswith(DOTENV_COMMENT_PREFIX):
                continue
            if DOTENV_SEPARATOR not in stripped_line:
                raise ValueError(f"dotenv 第 {line_number} 行格式无效。")
            key, value = stripped_line.split(DOTENV_SEPARATOR, maxsplit=1)
            normalized_key = key.strip()
            if normalized_key == "":
                raise ValueError(f"dotenv 第 {line_number} 行变量名为空。")
            variables[normalized_key] = self._normalize_value(value.strip())
        return variables

    def _normalize_value(self, value: str) -> str:
        """
        归一化 dotenv 变量值。

        :param value: dotenv 变量原始值。
        :type value: str
        :returns: 归一化后的变量值。
        :rtype: str
        """

        if len(value) >= 2 and (
            (value.startswith(DOTENV_DOUBLE_QUOTE) and value.endswith(DOTENV_DOUBLE_QUOTE))
            or (value.startswith(DOTENV_SINGLE_QUOTE) and value.endswith(DOTENV_SINGLE_QUOTE))
        ):
            return value[1:-1]
        return value
