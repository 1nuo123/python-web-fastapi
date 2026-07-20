"""
业务后台回归结果契约。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ADMIN_REGRESSION_SCHEMA_VERSION: Final = "1.0"
ADMIN_REGRESSION_RESULT_KIND: Final = "admin_regression_result"
ADMIN_REGRESSION_OPERATION_NAME: Final = "admin_regression"
ADMIN_REGRESSION_ENTRY_MAXIMUM_LENGTH = 256
ADMIN_REGRESSION_NOTE_MAXIMUM_LENGTH = 512


class AdminRegressionStatus(StrEnum):
    """
    业务后台回归状态枚举。
    """

    PASSED = "passed"
    FAILED = "failed"


class AdminRegressionHeader(BaseModel):
    """
    业务后台回归公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_regression_result"] = ADMIN_REGRESSION_RESULT_KIND
    schema_version: Literal["1.0"] = ADMIN_REGRESSION_SCHEMA_VERSION
    operation_name: Literal["admin_regression"] = ADMIN_REGRESSION_OPERATION_NAME


class AdminRegressionResultPayload(BaseModel):
    """
    业务后台回归结果扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_regression_result"] = ADMIN_REGRESSION_RESULT_KIND
    schema_version: Literal["1.0"] = ADMIN_REGRESSION_SCHEMA_VERSION
    status: AdminRegressionStatus
    test_entries: list[str] = Field(
        min_length=1,
        max_length=ADMIN_REGRESSION_ENTRY_MAXIMUM_LENGTH,
    )
    failure_fixes: list[str] = Field(
        default_factory=list,
        max_length=ADMIN_REGRESSION_ENTRY_MAXIMUM_LENGTH,
    )
    remaining_risks: list[str] = Field(
        default_factory=list,
        max_length=ADMIN_REGRESSION_ENTRY_MAXIMUM_LENGTH,
    )
    note: str | None = Field(default=None, max_length=ADMIN_REGRESSION_NOTE_MAXIMUM_LENGTH)


AdminRegressionDetailUnion = Annotated[
    AdminRegressionResultPayload,
    Field(discriminator="kind"),
]


class AdminRegressionResult(BaseModel):
    """
    业务后台回归结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminRegressionHeader
    detail: AdminRegressionDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminRegressionResult:
        """
        校验业务后台回归公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminRegressionResult
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("业务后台回归 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("业务后台回归 schema_version 必须一致。")
        return self
