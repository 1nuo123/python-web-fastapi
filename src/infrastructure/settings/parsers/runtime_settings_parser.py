"""
运行时配置分节解析器基础设施模块。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

AUTH_RUNTIME_SECTION_KEY: Final = "auth"
CACHE_RUNTIME_SECTION_KEY: Final = "cache"
DATABASE_RUNTIME_SECTION_KEY: Final = "database"
DISTRIBUTED_LOCK_RUNTIME_SECTION_KEY: Final = "distributed_lock"
KEY_MANAGEMENT_RUNTIME_SECTION_KEY: Final = "key_management"
LOGGING_RUNTIME_SECTION_KEY: Final = "logging"
MESSAGE_RUNTIME_SECTION_KEY: Final = "message"
METRICS_RUNTIME_SECTION_KEY: Final = "metrics"
OTEL_RUNTIME_SECTION_KEY: Final = "otel"
RUNTIME_SECTION_KEY: Final = "runtime"
TASK_RUNTIME_SECTION_KEY: Final = "task"
STREAM_RUNTIME_SECTION_KEY: Final = "stream"
WEB_RUNTIME_SECTION_KEY: Final = "web"
SECURITY_RUNTIME_SECTION_KEY: Final = "security"
AUTH_RUNTIME_DIRECTORY_NAME = "auth_runtime"
CACHE_RUNTIME_DIRECTORY_NAME = "cache_runtime"
DATABASE_RUNTIME_DIRECTORY_NAME = "database_runtime"
DISTRIBUTED_LOCK_RUNTIME_DIRECTORY_NAME = "distributed_lock_runtime"
KEY_MANAGEMENT_RUNTIME_DIRECTORY_NAME = "key_management_runtime"
LOGGING_RUNTIME_DIRECTORY_NAME = "logging_runtime"
MESSAGE_RUNTIME_DIRECTORY_NAME = "message_runtime"
METRICS_RUNTIME_DIRECTORY_NAME = "metrics_runtime"
OTEL_RUNTIME_DIRECTORY_NAME = "otel_runtime"
SECURITY_RUNTIME_DIRECTORY_NAME = "security_runtime"
TASK_RUNTIME_DIRECTORY_NAME = "task_runtime"
STREAM_RUNTIME_DIRECTORY_NAME = "stream_runtime"
WEB_RUNTIME_DIRECTORY_NAME = "web_runtime"
SETTINGS_SECTION_SCHEMA_VERSION: Final = "1.0"
SETTINGS_SECTION_HEADER_KIND: Final = "settings_section_header"
RUNTIME_SETTINGS_SECTION_DETAIL_KIND: Final = "runtime_settings_section_detail"


class SettingsSectionHeader(BaseModel):
    """
    配置节公共头。
    """

    model_config = ConfigDict(extra="forbid")

    header_kind: Literal["settings_section_header"] = SETTINGS_SECTION_HEADER_KIND
    schema_version: Literal["1.0"] = SETTINGS_SECTION_SCHEMA_VERSION
    section_name: str
    source_path: str


class RuntimeSettingsSectionDetail(BaseModel):
    """
    运行时配置节扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["runtime_settings_section_detail"] = RUNTIME_SETTINGS_SECTION_DETAIL_KIND
    schema_version: Literal["1.0"] = SETTINGS_SECTION_SCHEMA_VERSION
    runtime_key: Literal[
        "web",
        "security",
        "auth",
        "database",
        "distributed_lock",
        "key_management",
        "cache",
        "message",
        "task",
        "otel",
        "logging",
        "metrics",
        "stream",
    ]
    section_value: dict[str, object]


SettingsSectionDetail = Annotated[
    RuntimeSettingsSectionDetail,
    Field(discriminator="kind"),
]


class SettingsSectionEnvelope(BaseModel):
    """
    配置节信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: SettingsSectionHeader
    detail: SettingsSectionDetail


class RuntimeSettingsParser:
    """
    运行时配置分节解析器。
    """

    def parse_section(
        self,
        *,
        file_path: Path,
        file_content: dict[str, object],
    ) -> SettingsSectionEnvelope | None:
        """
        解析运行时配置分节。

        :param file_path: 当前读取的配置文件路径。
        :type file_path: Path
        :param file_content: 当前文件的 TOML 内容。
        :type file_content: dict[str, object]
        :returns: 返回已解析的运行时配置分节；若当前文件不属于运行时分节则返回 ``None``。
        :rtype: ParsedRuntimeSection | None
        """

        if WEB_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=WEB_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if SECURITY_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=SECURITY_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if AUTH_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=AUTH_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if DATABASE_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=DATABASE_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if DISTRIBUTED_LOCK_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=DISTRIBUTED_LOCK_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if KEY_MANAGEMENT_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=KEY_MANAGEMENT_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if CACHE_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=CACHE_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if MESSAGE_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=MESSAGE_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if TASK_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=TASK_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if OTEL_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=OTEL_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if METRICS_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=METRICS_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if LOGGING_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=LOGGING_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        if STREAM_RUNTIME_DIRECTORY_NAME in file_path.parts:
            return self._build_runtime_section(
                file_path=file_path,
                runtime_key=STREAM_RUNTIME_SECTION_KEY,
                file_content=file_content,
            )
        return None

    def _build_runtime_section(
        self,
        *,
        file_path: Path,
        runtime_key: Literal[
            "web",
            "security",
            "auth",
            "database",
            "distributed_lock",
            "key_management",
            "cache",
            "message",
            "task",
            "otel",
            "logging",
            "metrics",
            "stream",
        ],
        file_content: dict[str, object],
    ) -> SettingsSectionEnvelope:
        """
        构建运行时分节映射。

        :param runtime_key: 当前运行时分节键名。
        :type runtime_key: str
        :param file_content: 当前文件的 TOML 内容。
        :type file_content: dict[str, object]
        :returns: 返回运行时分节映射。
        :rtype: ParsedRuntimeSection
        """

        section_value = file_content.get(RUNTIME_SECTION_KEY, {})
        runtime_mapping = section_value if isinstance(section_value, dict) else {}
        return SettingsSectionEnvelope(
            header=SettingsSectionHeader(
                section_name=runtime_key,
                source_path=str(file_path),
            ),
            detail=RuntimeSettingsSectionDetail(
                runtime_key=runtime_key,
                section_value=runtime_mapping,
            ),
        )

    def extract_mapping(
        self,
        envelope: SettingsSectionEnvelope,
    ) -> dict[str, dict[str, dict[str, object]]]:
        """
        从运行时配置节信封提取配置映射。
        """

        return {RUNTIME_SECTION_KEY: {envelope.detail.runtime_key: envelope.detail.section_value}}
