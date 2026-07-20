"""
授权策略契约核心契约模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

AUTHORIZATION_POLICY_SCHEMA_VERSION: Final = "1.0"
AUTHORIZATION_POLICY_KIND: Final = "authorization_policy"
ROUTE_AUTHORIZATION_REQUIREMENT_KIND: Final = "route_authorization_requirement"
ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION: Final = "1.0"


class AuthorizationPolicy(BaseModel):
    """
    授权策略Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[AUTHORIZATION_POLICY_KIND]`` 注解；取值固定为 ``AUTHORIZATION_POLICY_KIND``。默认值：`AUTHORIZATION_POLICY_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[AUTHORIZATION_POLICY_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[AUTHORIZATION_POLICY_SCHEMA_VERSION]`` 注解；取值固定为 ``AUTHORIZATION_POLICY_SCHEMA_VERSION``。默认值：`AUTHORIZATION_POLICY_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[AUTHORIZATION_POLICY_SCHEMA_VERSION]
    :ivar required_scopes: 授权要求中的必需作用域。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于声明授权作用域或请求作用域。
    :vartype required_scopes: list[str]
    :ivar required_roles: 授权要求中的必需角色。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于描述角色标识或角色关联关系。
    :vartype required_roles: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["authorization_policy"] = Field(default=AUTHORIZATION_POLICY_KIND)
    schema_version: Literal["1.0"] = Field(default=AUTHORIZATION_POLICY_SCHEMA_VERSION)
    required_scopes: list[str] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class AuthorizationDecision:
    """
    授权决策数据对象，用于承载当前流程的结构化字段。

    :ivar allowed: ``allowed`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype allowed: bool
    :ivar reason: 失败原因。约束：需符合 ``str | None`` 注解；允许为空值。默认值：`None`。取值语义：用于承载当前对象中的业务状态。
    :vartype reason: str | None
    """

    allowed: bool
    reason: str | None = None


class RouteAuthorizationRequirement(BaseModel):
    """
    路由授权要求Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[ROUTE_AUTHORIZATION_REQUIREMENT_KIND]`` 注解；取值固定为 ``ROUTE_AUTHORIZATION_REQUIREMENT_KIND``。默认值：`ROUTE_AUTHORIZATION_REQUIREMENT_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[ROUTE_AUTHORIZATION_REQUIREMENT_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION]`` 注解；取值固定为 ``ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION``。默认值：`ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION]
    :ivar requirement_name: ``requirement_name`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype requirement_name: str
    :ivar required_scopes: 授权要求中的必需作用域。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于声明授权作用域或请求作用域。
    :vartype required_scopes: list[str]
    :ivar required_roles: 授权要求中的必需角色。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：由 ``list`` 动态生成。取值语义：用于描述角色标识或角色关联关系。
    :vartype required_roles: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["route_authorization_requirement"] = ROUTE_AUTHORIZATION_REQUIREMENT_KIND
    schema_version: Literal["1.0"] = ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION
    requirement_name: str
    required_scopes: list[str] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)

    def to_policy(self) -> AuthorizationPolicy:
        """
        处理到策略。

        :returns: 返回当前操作结果。
        :rtype: AuthorizationPolicy
        """

        return AuthorizationPolicy(
            required_scopes=self.required_scopes,
            required_roles=self.required_roles,
        )
