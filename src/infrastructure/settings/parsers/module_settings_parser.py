"""
模块配置分节解析器基础设施模块。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

APP_SECTION_KEY: Final = "app"
AUTH_MODULE_SECTION_KEY: Final = "auth_module"
MODULE_SECTION_KEY: Final = "module"
SYSTEM_MODULE_SECTION_KEY: Final = "system_module"
TASK_MODULE_SECTION_KEY: Final = "task_module"
SETTINGS_SECTION_SCHEMA_VERSION: Final = "1.0"
SETTINGS_SECTION_HEADER_KIND: Final = "settings_section_header"
MODULE_SETTINGS_SECTION_DETAIL_KIND: Final = "module_settings_section_detail"
APP_SETTINGS_SECTION_DETAIL_KIND: Final = "app_settings_section_detail"


class SettingsSectionHeader(BaseModel):
    """
    配置节公共头。
    """

    model_config = ConfigDict(extra="forbid")

    header_kind: Literal["settings_section_header"] = SETTINGS_SECTION_HEADER_KIND
    schema_version: Literal["1.0"] = SETTINGS_SECTION_SCHEMA_VERSION
    section_name: str
    source_path: str


class AppSettingsSectionDetail(BaseModel):
    """
    应用配置节扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["app_settings_section_detail"] = APP_SETTINGS_SECTION_DETAIL_KIND
    schema_version: Literal["1.0"] = SETTINGS_SECTION_SCHEMA_VERSION
    app: dict[str, object]


class ModuleSettingsSectionDetail(BaseModel):
    """
    模块配置节扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["module_settings_section_detail"] = MODULE_SETTINGS_SECTION_DETAIL_KIND
    schema_version: Literal["1.0"] = SETTINGS_SECTION_SCHEMA_VERSION
    target_key: Literal["system_module", "auth_module", "task_module"]
    section_value: dict[str, object]


SettingsSectionDetail = Annotated[
    AppSettingsSectionDetail | ModuleSettingsSectionDetail,
    Field(discriminator="kind"),
]


class SettingsSectionEnvelope(BaseModel):
    """
    配置节信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: SettingsSectionHeader
    detail: SettingsSectionDetail


class ModuleSettingsParser:
    """
    模块配置分节解析器。
    """

    def parse_section(
        self,
        *,
        file_path: Path,
        file_content: dict[str, object],
    ) -> SettingsSectionEnvelope | None:
        """
        解析模块配置分节。

        :param file_path: 当前读取的配置文件路径。
        :type file_path: Path
        :param file_content: 当前文件的 TOML 内容。
        :type file_content: dict[str, object]
        :returns: 返回已解析的模块配置分节；若当前文件不属于模块分节则返回 ``None``。
        :rtype: ParsedSettingsSection | None
        """

        if file_path.name.startswith("app_"):
            return SettingsSectionEnvelope(
                header=self._build_header(file_path=file_path, section_name=APP_SECTION_KEY),
                detail=AppSettingsSectionDetail(
                    app=self._read_mapping(file_content, APP_SECTION_KEY)
                ),
            )
        if SYSTEM_MODULE_SECTION_KEY in file_path.parts:
            return self._build_module_envelope(
                file_path=file_path,
                target_key=SYSTEM_MODULE_SECTION_KEY,
                file_content=file_content,
            )
        if AUTH_MODULE_SECTION_KEY in file_path.parts:
            return self._build_module_envelope(
                file_path=file_path,
                target_key=AUTH_MODULE_SECTION_KEY,
                file_content=file_content,
            )
        if TASK_MODULE_SECTION_KEY in file_path.parts:
            return self._build_module_envelope(
                file_path=file_path,
                target_key=TASK_MODULE_SECTION_KEY,
                file_content=file_content,
            )
        return None

    def extract_mapping(
        self,
        envelope: SettingsSectionEnvelope,
    ) -> dict[str, dict[str, object]]:
        """
        从配置节信封提取配置映射。
        """

        if isinstance(envelope.detail, AppSettingsSectionDetail):
            return {APP_SECTION_KEY: envelope.detail.app}
        return {envelope.detail.target_key: envelope.detail.section_value}

    def _read_mapping(
        self,
        file_content: dict[str, object],
        section_key: str,
    ) -> dict[str, object]:
        """
        读取目标分节映射。

        :param file_content: 当前文件的 TOML 内容。
        :type file_content: dict[str, object]
        :param section_key: 当前目标分节键名。
        :type section_key: str
        :returns: 返回分节映射。
        :rtype: dict[str, object]
        """

        section_value = file_content.get(section_key, {})
        if isinstance(section_value, dict):
            return section_value
        return {}

    def _build_header(
        self,
        *,
        file_path: Path,
        section_name: str,
    ) -> SettingsSectionHeader:
        """
        构建配置节公共头。
        """

        return SettingsSectionHeader(
            section_name=section_name,
            source_path=str(file_path),
        )

    def _build_module_envelope(
        self,
        *,
        file_path: Path,
        target_key: Literal["system_module", "auth_module", "task_module"],
        file_content: dict[str, object],
    ) -> SettingsSectionEnvelope:
        """
        构建模块配置节信封。
        """

        return SettingsSectionEnvelope(
            header=self._build_header(file_path=file_path, section_name=target_key),
            detail=ModuleSettingsSectionDetail(
                target_key=target_key,
                section_value=self._read_mapping(file_content, MODULE_SECTION_KEY),
            ),
        )
