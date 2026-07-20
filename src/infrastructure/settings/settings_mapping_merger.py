"""
配置映射合并器。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

SETTINGS_MERGE_SCHEMA_VERSION: Final = "1.0"
SETTINGS_MERGE_HEADER_KIND: Final = "settings_merge"
RECURSIVE_MAPPING_MERGE_KIND: Final = "recursive_mapping_merge"
DEFAULT_SETTINGS_MERGE_NAME = "application_settings_merge"
DISCRIMINATOR_FIELD_NAME = "kind"

SettingsScalar: TypeAlias = str | int | float | bool | None
SettingsMappingValue: TypeAlias = (
    SettingsScalar | list["SettingsMappingValue"] | dict[str, "SettingsMappingValue"]
)
SettingsMapping: TypeAlias = dict[str, SettingsMappingValue]
SettingsMappingInput: TypeAlias = Mapping[str, SettingsMappingValue]


class SettingsMergeHeader(BaseModel):
    """
    配置合并公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["settings_merge"] = SETTINGS_MERGE_HEADER_KIND
    schema_version: Literal["1.0"] = SETTINGS_MERGE_SCHEMA_VERSION
    merge_name: str = DEFAULT_SETTINGS_MERGE_NAME


class RecursiveMappingMergeDetail(BaseModel):
    """
    递归映射合并扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["recursive_mapping_merge"] = RECURSIVE_MAPPING_MERGE_KIND
    schema_version: Literal["1.0"] = SETTINGS_MERGE_SCHEMA_VERSION
    discriminator_field_name: str = DISCRIMINATOR_FIELD_NAME


SettingsMergeDetail = Annotated[
    RecursiveMappingMergeDetail,
    Field(discriminator="kind"),
]


class SettingsMergeEnvelope(BaseModel):
    """
    配置合并信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: SettingsMergeHeader
    detail: SettingsMergeDetail

    @model_validator(mode="after")
    def validate_merge_contract(self) -> SettingsMergeEnvelope:
        """
        校验合并信封公共头与扩展字段一致。
        """

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("配置合并 header.schema_version 必须与 detail.schema_version 一致。")
        return self


class SettingsMappingMerger:
    """
    配置映射合并器。
    """

    def __init__(self) -> None:
        """
        初始化配置映射合并器。
        """

        self.contract = SettingsMergeEnvelope(
            header=SettingsMergeHeader(),
            detail=RecursiveMappingMergeDetail(),
        )

    def merge(
        self,
        base_value: SettingsMappingInput,
        override_value: SettingsMappingInput,
    ) -> SettingsMapping:
        """
        合并配置映射。

        :param base_value: 递归合并时的基准映射。
        :type base_value: SettingsMappingInput
        :param override_value: 递归合并时的覆盖映射。
        :type override_value: SettingsMappingInput
        :returns: 合并后的配置映射。
        :rtype: SettingsMapping
        """

        merged: SettingsMapping = dict(base_value)
        for key, override_item in override_value.items():
            base_item = merged.get(key)
            if isinstance(base_item, dict) and isinstance(override_item, dict):
                base_kind = base_item.get(DISCRIMINATOR_FIELD_NAME)
                override_kind = override_item.get(DISCRIMINATOR_FIELD_NAME)
                if (
                    isinstance(base_kind, str)
                    and isinstance(override_kind, str)
                    and base_kind != override_kind
                ):
                    # 联合类型明细切换 kind 时整段替换，避免残留上一个后端的字段。
                    merged[key] = dict(override_item)
                    continue
                merged[key] = self.merge(base_item, override_item)
                continue
            merged[key] = override_item
        return merged
