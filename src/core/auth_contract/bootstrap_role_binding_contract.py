"""
引导角色绑定契约核心契约模块。
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

BOOTSTRAP_ROLE_BINDING_KIND: Final = "bootstrap_role_binding"
BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION: Final = "v1"


class BootstrapRoleBindingV1(BaseModel):
    """
    引导角色绑定V1Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[BOOTSTRAP_ROLE_BINDING_KIND]`` 注解；取值固定为 ``BOOTSTRAP_ROLE_BINDING_KIND``。默认值：`BOOTSTRAP_ROLE_BINDING_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[BOOTSTRAP_ROLE_BINDING_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION]`` 注解；取值固定为 ``BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION``。默认值：`BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION]
    :ivar role_key: ``role_key`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于描述角色标识或角色关联关系。
    :vartype role_key: str
    :ivar scope_codes: 作用域编码列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于声明授权作用域或请求作用域。
    :vartype scope_codes: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["bootstrap_role_binding"] = BOOTSTRAP_ROLE_BINDING_KIND
    schema_version: Literal["v1"] = BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION
    role_key: str
    scope_codes: list[str]


BootstrapRoleBinding = Annotated[
    BootstrapRoleBindingV1,
    Field(discriminator="kind"),
]
