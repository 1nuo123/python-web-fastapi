"""
鉴权身份仓储契约核心契约模块。
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from uuid import UUID

from src.core.auth_contract.auth_identity_authorization_snapshot_contract import (
    AuthIdentityAuthorizationSnapshot,
)
from src.core.auth_contract.auth_identity_status_contract import AuthIdentityStatusPayload
from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.persistence_contract.repository_contract import Repository


@dataclass(slots=True)
class AuthIdentitySnapshot:
    """
    鉴权身份数据对象，用于承载当前流程的结构化字段。

    :ivar user_id: 用户主键标识。约束：需符合 ``UUID`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype user_id: UUID
    :ivar subject_id: 认证主体标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str
    :ivar username: 登录用户名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str
    :ivar password_hash: 密码哈希值。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_hash: str
    :ivar is_active: 主体是否处于激活状态。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示当前状态成立，``False`` 表示当前状态不成立。
    :vartype is_active: bool
    :ivar roles: 角色键列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于描述角色标识或角色关联关系。
    :vartype roles: list[str]
    :ivar scopes: 作用域编码列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于声明授权作用域或请求作用域。
    :vartype scopes: list[str]
    """

    user_id: UUID
    subject_id: str
    username: str
    password_hash: str
    is_active: bool
    roles: list[str]
    scopes: list[str]

    def to_authenticated_principal(self) -> AuthenticatedPrincipal:
        """
        处理到已认证主体。

        :returns: 返回当前操作结果。
        :rtype: AuthenticatedPrincipal
        """

        return AuthenticatedPrincipal(
            subject_id=self.subject_id,
            username=self.username,
            roles=self.roles,
            scopes=self.scopes,
        )


class AuthIdentityRepository(Repository):
    """
    鉴权身份抽象基类，定义需要由实现类完成的方法契约。
    """

    @abstractmethod
    def get_by_username(self, username: str) -> AuthIdentitySnapshot | None:
        """
        获取按用户名。

        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentitySnapshot | None
        """

        pass

    @abstractmethod
    def get_by_subject_id(self, subject_id: str) -> AuthIdentitySnapshot | None:
        """
        获取按主体标识。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentitySnapshot | None
        """

        pass

    @abstractmethod
    def get_authorization_snapshot_by_subject_id(
        self,
        subject_id: str,
    ) -> AuthIdentityAuthorizationSnapshot | None:
        """
        获取授权快照按主体标识。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentityAuthorizationSnapshot | None
        """

        pass

    @abstractmethod
    def get_status_by_subject_id(
        self,
        subject_id: str,
    ) -> AuthIdentityStatusPayload | None:
        """
        获取状态按主体标识。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentityStatusPayload | None
        """

        pass

    @abstractmethod
    def update_password_hash(self, *, user_id: UUID, password_hash: str) -> None:
        """
        更新密码哈希。

        :param user_id: 用户主键标识。约束：需符合 ``UUID`` 注解。
        :type user_id: UUID
        :param password_hash: 持久化的密码哈希值。约束：需符合 ``str`` 注解。
        :type password_hash: str
        :returns: 无返回值。
        :rtype: None
        """

        pass
