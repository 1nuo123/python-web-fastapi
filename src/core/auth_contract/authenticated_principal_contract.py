"""
已认证主体契约核心契约模块。
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from src.core.auth_contract.auth_identity_authorization_snapshot_contract import (
    AuthIdentityAuthorizationSnapshot,
)

AUTH_PRINCIPAL_SCHEMA_VERSION: Final = "1.0"
AUTHENTICATED_PRINCIPAL_KIND: Final = "authenticated_principal"
AUTHENTICATED_PRINCIPAL_ADMIN_ROLE = "admin"


class AuthenticatedPrincipal(BaseModel):
    """
    已认证主体Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[AUTHENTICATED_PRINCIPAL_KIND]`` 注解；取值固定为 ``AUTHENTICATED_PRINCIPAL_KIND``。默认值：`AUTHENTICATED_PRINCIPAL_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[AUTHENTICATED_PRINCIPAL_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[AUTH_PRINCIPAL_SCHEMA_VERSION]`` 注解；取值固定为 ``AUTH_PRINCIPAL_SCHEMA_VERSION``。默认值：`AUTH_PRINCIPAL_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[AUTH_PRINCIPAL_SCHEMA_VERSION]
    :ivar subject_id: 认证主体标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str
    :ivar username: 登录用户名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str
    :ivar roles: 角色键列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于描述角色标识或角色关联关系。
    :vartype roles: list[str]
    :ivar scopes: 作用域编码列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于声明授权作用域或请求作用域。
    :vartype scopes: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["authenticated_principal"] = AUTHENTICATED_PRINCIPAL_KIND
    schema_version: Literal["1.0"] = AUTH_PRINCIPAL_SCHEMA_VERSION
    subject_id: str
    username: str
    roles: list[str]
    scopes: list[str]
    is_admin: bool = False

    @model_validator(mode="after")
    def derive_admin_flag(self) -> AuthenticatedPrincipal:
        """
        根据当前角色集合派生管理员标记。

        :returns: 当前认证主体。
        :rtype: AuthenticatedPrincipal
        """

        self.is_admin = AUTHENTICATED_PRINCIPAL_ADMIN_ROLE in {str(role) for role in self.roles}
        return self

    @classmethod
    def from_authorization_snapshot(
        cls,
        snapshot: AuthIdentityAuthorizationSnapshot,
    ) -> AuthenticatedPrincipal:
        """
        处理从授权快照。

        :param snapshot: 历史快照对象。约束：需符合 ``AuthIdentityAuthorizationSnapshot`` 注解。
        :type snapshot: AuthIdentityAuthorizationSnapshot
        :returns: 返回当前操作结果。
        :rtype: 'AuthenticatedPrincipal'
        """

        return cls(
            subject_id=snapshot.subject_id,
            username=snapshot.username,
            roles=snapshot.roles,
            scopes=snapshot.scopes,
        )
