"""公共契约头核心模块。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_SCHEMA_VERSION_MINIMUM_LENGTH = 1


class ContractHeader(BaseModel):
    """统一约束公共契约头的稳定版本字段。

    :ivar schema_version: 契约结构版本。约束：不能为空。取值语义：标识当前记录遵循的冻结契约版本。
    :vartype schema_version: str
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=CONTRACT_SCHEMA_VERSION_MINIMUM_LENGTH)
