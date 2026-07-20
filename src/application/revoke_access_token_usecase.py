"""
撤销访问令牌用例应用层模块。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus

from src.application.ports.auth_runtime_port import AuthRuntimePort
from src.core.auth_contract.token_payload_contract import TokenRevokePayload, TokenUse
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode

REFRESH_TOKEN_MISSING_MESSAGE = "刷新令牌不存在。"
REFRESH_TOKEN_SUBJECT_MISMATCH_MESSAGE = "刷新令牌主体不匹配。"
REFRESH_TOKEN_SESSION_MISMATCH_MESSAGE = "刷新令牌会话不匹配。"


@dataclass(slots=True)
class RevokeTokenInput:
    """
    撤销令牌数据对象，用于承载当前流程的结构化字段。

    :ivar refresh_token: ``refresh_token`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token: str
    """

    refresh_token: str


class RevokeTokenSessionUsecase:
    """
    撤销令牌会话应用用例，负责封装当前业务流程。
    """

    def __init__(self, *, runtime_port: AuthRuntimePort) -> None:
        """
        初始化撤销令牌会话用例。

        :param runtime_port: 鉴权运行时端口。
        :type runtime_port: AuthRuntimePort
        :returns: 无返回值。
        :rtype: None
        """

        self._runtime_port = runtime_port

    def execute(self, revoke_token_input: RevokeTokenInput) -> TokenRevokePayload:
        """
        执行撤销令牌会话主流程。

        :param revoke_token_input: 撤销令牌输入对象。约束：需符合 ``RevokeTokenInput`` 注解。
        :type revoke_token_input: RevokeTokenInput
        :returns: 返回当前业务流程产出的结果对象。
        :rtype: TokenRevokePayload
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        :raises Exception: 当底层依赖发生未预期故障时继续向上抛出。
        """

        current_epoch = int(time.time())
        token_service = self._runtime_port.get_jwt_token_service()
        token_payload = token_service.decode_token(
            revoke_token_input.refresh_token,
            expected_use=TokenUse.REFRESH,
            current_epoch=current_epoch,
        )
        refresh_token_id = token_payload.token_id
        token_session_id = token_payload.token_session_id
        unit_of_work = self._runtime_port.create_unit_of_work()
        try:
            # 撤销操作以刷新令牌会话为准，避免仅凭 JWT 自身状态做判断。
            session = unit_of_work.get_session()
            refresh_token_repository = self._runtime_port.create_refresh_token_repository(session)
            refresh_token_session = refresh_token_repository.get_by_token_id_for_update(
                refresh_token_id
            )
            if refresh_token_session is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_MISSING_MESSAGE,
                )
            if refresh_token_session.subject_id != token_payload.subject_id:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_SUBJECT_MISMATCH_MESSAGE,
                )
            if refresh_token_session.token_session_id != token_session_id:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_SESSION_MISMATCH_MESSAGE,
                )
            revoked_at = refresh_token_session.revoked_at or datetime.fromtimestamp(
                current_epoch,
                tz=UTC,
            )
            if refresh_token_session.revoked_at is None:
                # 首次撤销才写库；已撤销会话复用原撤销时间，保持接口幂等。
                refresh_token_repository.revoke_token_session(
                    token_session_id=token_session_id,
                    revoked_at=revoked_at,
                )
            unit_of_work.commit()
            return TokenRevokePayload(
                revoked=True,
                revoked_at_epoch=int(revoked_at.timestamp()),
            )
        except HttpFaultException:
            # 业务校验失败时不保留部分写入。
            unit_of_work.rollback()
            raise
        except Exception:
            # 基础设施异常沿原链路抛出前先回滚事务。
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
