"""
刷新访问令牌用例应用层模块。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.auth_runtime_port import (
    AuthFailureThrottlePort,
    AuthRuntimePort,
    IssuedTokenBundlePort,
)
from src.core.auth_contract.token_payload_contract import TokenIssuePayload, TokenUse
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.refresh_token_repository_contract import (
    RefreshTokenSessionPayload,
)
from src.domain.auth.auth_error_code import AuthErrorCode

REFRESH_TOKEN_THROTTLE_IP_MISSING = "unknown"
REFRESH_TOKEN_THROTTLE_PREFIX = "refresh_token"
REFRESH_TOKEN_THROTTLE_IP_FIELD = "ip"
REFRESH_TOKEN_THROTTLE_GLOBAL_FIELD = "global"
REFRESH_TOKEN_THROTTLE_SUBJECT_SEPARATOR = "|"
REFRESH_TOKEN_THROTTLE_FIELD_SEPARATOR = ":"

ACCOUNT_DISABLED_MESSAGE = "账号已停用。"
REFRESH_TOKEN_REUSED_MESSAGE = "刷新令牌已重复使用。"
REFRESH_TOKEN_REVOKED_MESSAGE = "刷新令牌已吊销。"
REFRESH_TOKEN_MISSING_MESSAGE = "刷新令牌不存在。"
REFRESH_TOKEN_SUBJECT_MISMATCH_MESSAGE = "刷新令牌主体不匹配。"
REFRESH_TOKEN_SESSION_MISMATCH_MESSAGE = "刷新令牌会话不匹配。"
REFRESH_TOKEN_SUBJECT_MISSING_MESSAGE = "刷新令牌主体不存在。"


@dataclass(slots=True)
class RefreshTokenInput:
    """
    刷新令牌数据对象，用于承载当前流程的结构化字段。

    :ivar refresh_token: ``refresh_token`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token: str
    """

    refresh_token: str
    client_ip: str | None = None

    def build_throttle_subject_key(self) -> str:
        """
        构建刷新令牌客户端 IP 节流主体键。

        :returns: 客户端 IP 维度的刷新令牌节流主体键。
        :rtype: str
        """

        client_ip = self.client_ip or REFRESH_TOKEN_THROTTLE_IP_MISSING
        return REFRESH_TOKEN_THROTTLE_SUBJECT_SEPARATOR.join(
            [
                REFRESH_TOKEN_THROTTLE_PREFIX,
                (
                    f"{REFRESH_TOKEN_THROTTLE_IP_FIELD}"
                    f"{REFRESH_TOKEN_THROTTLE_FIELD_SEPARATOR}{client_ip}"
                ),
            ]
        )

    def build_throttle_subject_keys(self) -> tuple[str, ...]:
        """
        构建刷新令牌失败节流主体键集合。

        :returns: 客户端 IP 与全局维度的刷新令牌节流主体键集合。
        :rtype: tuple[str, ...]
        """

        global_subject_key = REFRESH_TOKEN_THROTTLE_SUBJECT_SEPARATOR.join(
            [
                REFRESH_TOKEN_THROTTLE_PREFIX,
                REFRESH_TOKEN_THROTTLE_GLOBAL_FIELD,
            ]
        )
        return (self.build_throttle_subject_key(), global_subject_key)


class RefreshAccessTokenUsecase:
    """
    刷新访问令牌应用用例，负责封装当前业务流程。
    """

    def __init__(self, *, runtime_port: AuthRuntimePort) -> None:
        """
        初始化刷新访问令牌用例。

        :param runtime_port: 鉴权运行时端口。
        :type runtime_port: AuthRuntimePort
        :returns: 无返回值。
        :rtype: None
        """

        self._runtime_port = runtime_port

    def execute(self, refresh_token_input: RefreshTokenInput) -> TokenIssuePayload:
        """
        执行刷新访问令牌主流程。

        :param refresh_token_input: 刷新令牌输入对象。约束：需符合 ``RefreshTokenInput`` 注解。
        :type refresh_token_input: RefreshTokenInput
        :returns: 返回当前业务流程产出的结果对象。
        :rtype: TokenIssuePayload
        :raises Exception: 当底层依赖发生未预期故障时继续向上抛出。
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        auth_failure_throttle = self._runtime_port.get_auth_failure_throttle()
        throttle_subject_keys = refresh_token_input.build_throttle_subject_keys()
        for throttle_subject_key in throttle_subject_keys:
            auth_failure_throttle.assert_refresh_access_token_allowed(throttle_subject_key)
        current_epoch = int(time.time())
        token_service = self._runtime_port.get_jwt_token_service()
        try:
            # 先做纯令牌级校验，尽量在进入数据库事务前拦截明显无效的刷新令牌。
            token_payload = token_service.decode_token(
                refresh_token_input.refresh_token,
                expected_use=TokenUse.REFRESH,
                current_epoch=current_epoch,
            )
        except Exception:
            self._record_refresh_access_token_failures(
                auth_failure_throttle,
                throttle_subject_keys,
            )
            raise
        refresh_token_id = token_payload.token_id
        token_session_id = token_payload.token_session_id
        unit_of_work = self._runtime_port.create_unit_of_work()
        reuse_revocation_committed = False
        try:
            # 数据库中的会话记录是刷新链路的真实来源，必须再次核对主体、会话和撤销状态。
            session = unit_of_work.get_session()
            refresh_token_repository = self._runtime_port.create_refresh_token_repository(session)
            refresh_token_session = refresh_token_repository.get_by_token_id_for_update(
                refresh_token_id
            )
            if refresh_token_session is None:
                self._record_refresh_access_token_failures(
                    auth_failure_throttle,
                    throttle_subject_keys,
                )
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_MISSING_MESSAGE,
                )
            if refresh_token_session.subject_id != token_payload.subject_id:
                self._record_refresh_access_token_failures(
                    auth_failure_throttle,
                    throttle_subject_keys,
                )
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_SUBJECT_MISMATCH_MESSAGE,
                )
            if refresh_token_session.token_session_id != token_session_id:
                self._record_refresh_access_token_failures(
                    auth_failure_throttle,
                    throttle_subject_keys,
                )
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_SESSION_MISMATCH_MESSAGE,
                )
            if refresh_token_session.rotated_to_token_id is not None:
                self._record_refresh_access_token_failures(
                    auth_failure_throttle,
                    throttle_subject_keys,
                )
                revoked_at = datetime.fromtimestamp(current_epoch, tz=UTC)
                refresh_token_repository.revoke_token_session(
                    token_session_id=token_session_id,
                    revoked_at=revoked_at,
                )
                unit_of_work.commit()
                reuse_revocation_committed = True
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_REUSED,
                    message=REFRESH_TOKEN_REUSED_MESSAGE,
                )
            if refresh_token_session.revoked_at is not None:
                self._record_refresh_access_token_failures(
                    auth_failure_throttle,
                    throttle_subject_keys,
                )
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_REVOKED,
                    message=REFRESH_TOKEN_REVOKED_MESSAGE,
                )
            auth_identity_repository = self._runtime_port.create_auth_identity_repository(session)
            auth_identity = auth_identity_repository.get_by_subject_id(token_payload.subject_id)
            if auth_identity is None:
                self._record_refresh_access_token_failures(
                    auth_failure_throttle,
                    throttle_subject_keys,
                )
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=REFRESH_TOKEN_SUBJECT_MISSING_MESSAGE,
                )
            if not auth_identity.is_active:
                raise HttpFaultException(
                    status_code=HTTPStatus.FORBIDDEN,
                    error_code=AuthErrorCode.ACCOUNT_DISABLED,
                    message=ACCOUNT_DISABLED_MESSAGE,
                )
            issued_token_bundle = token_service.issue_token_pair(
                auth_identity.to_authenticated_principal(),
                current_epoch=current_epoch,
                token_session_id=token_payload.token_session_id,
            )
            refresh_token_repository.create(
                self._build_refresh_token_session_payload(
                    auth_identity.user_id,
                    auth_identity.subject_id,
                    issued_token_bundle,
                )
            )
            revoked_at = datetime.fromtimestamp(current_epoch, tz=UTC)
            # 旧刷新令牌行已加锁；先写入新令牌再标记旧令牌，避免自关联外键悬挂。
            refresh_token_repository.mark_token_rotated(
                refresh_token_id=refresh_token_id,
                rotated_to_token_id=issued_token_bundle.refresh_token_payload.token_id,
                revoked_at=revoked_at,
            )
            unit_of_work.commit()
            self._clear_refresh_access_token_failures(
                auth_failure_throttle,
                throttle_subject_keys,
            )
            return issued_token_bundle.response_payload
        except HttpFaultException:
            # 轮换链路任一业务校验失败都要回滚旧会话修改。
            if not reuse_revocation_committed:
                unit_of_work.rollback()
            raise
        except Exception:
            # 非预期异常保持原样抛出，但先恢复事务边界内的数据库状态。
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _record_refresh_access_token_failures(
        self,
        auth_failure_throttle: AuthFailureThrottlePort,
        throttle_subject_keys: tuple[str, ...],
    ) -> None:
        """
        记录刷新令牌失败节流计数。

        :param auth_failure_throttle: 鉴权失败节流器。
        :type auth_failure_throttle: object
        :param throttle_subject_keys: 节流主体键集合。
        :type throttle_subject_keys: tuple[str, ...]
        :returns: 无返回值。
        :rtype: None
        """

        for throttle_subject_key in throttle_subject_keys:
            auth_failure_throttle.record_refresh_access_token_failure(throttle_subject_key)

    def _clear_refresh_access_token_failures(
        self,
        auth_failure_throttle: AuthFailureThrottlePort,
        throttle_subject_keys: tuple[str, ...],
    ) -> None:
        """
        清理刷新令牌失败节流计数。

        :param auth_failure_throttle: 鉴权失败节流器。
        :type auth_failure_throttle: object
        :param throttle_subject_keys: 节流主体键集合。
        :type throttle_subject_keys: tuple[str, ...]
        :returns: 无返回值。
        :rtype: None
        """

        for throttle_subject_key in throttle_subject_keys:
            auth_failure_throttle.clear_refresh_access_token_failures(throttle_subject_key)

    def _build_refresh_token_session_payload(
        self,
        user_id: UUID,
        subject_id: str,
        issued_token_bundle: IssuedTokenBundlePort,
    ) -> RefreshTokenSessionPayload:
        """
        构建刷新令牌会话载荷。

        :param user_id: 用户主键标识。约束：需符合 ``UUID`` 注解。
        :type user_id: UUID
        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :param issued_token_bundle: JWT 服务生成的成对令牌结果。约束：需符合 ``IssuedTokenBundle`` 注解。
        :type issued_token_bundle: IssuedTokenBundle
        :returns: 返回当前操作结果。
        :rtype: RefreshTokenSessionPayload
        """

        refresh_token_payload = issued_token_bundle.refresh_token_payload
        return RefreshTokenSessionPayload(
            refresh_token_id=refresh_token_payload.token_id,
            token_session_id=refresh_token_payload.token_session_id,
            user_id=user_id,
            subject_id=subject_id,
            issued_at=datetime.fromtimestamp(
                refresh_token_payload.issued_at_epoch,
                tz=UTC,
            ),
            expires_at=datetime.fromtimestamp(
                refresh_token_payload.expires_at_epoch,
                tz=UTC,
            ),
        )
