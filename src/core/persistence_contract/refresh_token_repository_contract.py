"""
刷新令牌仓储契约核心契约模块。
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.core.auth_contract.token_session_status_contract import TokenSessionStatusPayload
from src.core.persistence_contract.repository_contract import Repository

REFRESH_TOKEN_SESSION_KIND: Final = "refresh_token_session"
REFRESH_TOKEN_SESSION_SCHEMA_VERSION: Final = "1.0"


class RefreshTokenSessionPayload(BaseModel):
    """
    刷新令牌会话Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[REFRESH_TOKEN_SESSION_KIND]`` 注解；取值固定为 ``REFRESH_TOKEN_SESSION_KIND``。默认值：`REFRESH_TOKEN_SESSION_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[REFRESH_TOKEN_SESSION_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[REFRESH_TOKEN_SESSION_SCHEMA_VERSION]`` 注解；取值固定为 ``REFRESH_TOKEN_SESSION_SCHEMA_VERSION``。默认值：`REFRESH_TOKEN_SESSION_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[REFRESH_TOKEN_SESSION_SCHEMA_VERSION]
    :ivar refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype refresh_token_id: UUID
    :ivar token_session_id: 令牌会话标识。约束：需符合 ``UUID`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype token_session_id: UUID
    :ivar user_id: 用户主键标识。约束：需符合 ``UUID`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype user_id: UUID
    :ivar subject_id: 认证主体标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str
    :ivar issued_at: 签发时间。约束：需符合 ``datetime`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype issued_at: datetime
    :ivar expires_at: 过期时间。约束：需符合 ``datetime`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype expires_at: datetime
    :ivar revoked_at: 撤销时间。约束：需符合 ``datetime | None`` 注解；允许为空值。默认值：`None`。取值语义：用于承载当前对象中的业务状态。
    :vartype revoked_at: datetime | None
    :ivar rotated_to_token_id: 轮换后的新刷新令牌标识。约束：需符合 ``UUID | None`` 注解；允许为空值。默认值：`None`。取值语义：用于唯一标识对应实体。
    :vartype rotated_to_token_id: UUID | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["refresh_token_session"] = REFRESH_TOKEN_SESSION_KIND
    schema_version: Literal["1.0"] = REFRESH_TOKEN_SESSION_SCHEMA_VERSION
    refresh_token_id: UUID
    token_session_id: UUID
    user_id: UUID
    subject_id: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    rotated_to_token_id: UUID | None = None


class RefreshTokenRepository(Repository):
    """
    刷新令牌抽象基类，定义需要由实现类完成的方法契约。
    """

    @abstractmethod
    def create(self, refresh_token_session: RefreshTokenSessionPayload) -> None:
        """
        处理创建。

        :param refresh_token_session: 刷新令牌会话实体。约束：需符合 ``RefreshTokenSessionPayload`` 注解。
        :type refresh_token_session: RefreshTokenSessionPayload
        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def get_by_token_id(self, refresh_token_id: UUID) -> RefreshTokenSessionPayload | None:
        """
        获取按令牌标识。

        :param refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type refresh_token_id: UUID
        :returns: 返回读取到的对象或状态快照。
        :rtype: RefreshTokenSessionPayload | None
        """

        pass

    @abstractmethod
    def get_by_token_id_for_update(
        self,
        refresh_token_id: UUID,
    ) -> RefreshTokenSessionPayload | None:
        """
        获取按令牌标识用于更新。

        :param refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type refresh_token_id: UUID
        :returns: 返回读取到的对象或状态快照。
        :rtype: RefreshTokenSessionPayload | None
        """

        pass

    @abstractmethod
    def get_token_session_status(
        self,
        token_session_id: UUID,
    ) -> TokenSessionStatusPayload | None:
        """
        获取令牌会话状态。

        :param token_session_id: 令牌会话标识，用于串联一组访问令牌与刷新令牌。约束：需符合 ``UUID`` 注解。
        :type token_session_id: UUID
        :returns: 返回读取到的对象或状态快照。
        :rtype: TokenSessionStatusPayload | None
        """

        pass

    @abstractmethod
    def mark_token_rotated(
        self,
        *,
        refresh_token_id: UUID,
        rotated_to_token_id: UUID,
        revoked_at: datetime,
    ) -> None:
        """
        标记令牌轮换。

        :param refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type refresh_token_id: UUID
        :param rotated_to_token_id: 轮换后的新刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type rotated_to_token_id: UUID
        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def revoke_token_session(
        self,
        *,
        token_session_id: UUID,
        revoked_at: datetime,
    ) -> int:
        """
        撤销令牌会话。

        :param token_session_id: 令牌会话标识，用于串联一组访问令牌与刷新令牌。约束：需符合 ``UUID`` 注解。
        :type token_session_id: UUID
        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 返回当前操作结果。
        :rtype: int
        """

        pass

    @abstractmethod
    def revoke_active_token_sessions_by_subject_id(
        self,
        *,
        subject_id: str,
        revoked_at: datetime,
    ) -> int:
        """
        按主体标识撤销全部活跃刷新令牌会话。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 返回被撤销的刷新令牌记录数量。
        :rtype: int
        """

        pass

    @abstractmethod
    def revoke_all_active_token_sessions(self, *, revoked_at: datetime) -> int:
        """
        撤销全部仍处于活跃状态的刷新令牌会话。

        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 返回被撤销的刷新令牌记录数量。
        :rtype: int
        """

        pass
