"""
签发访问令牌用例应用层模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.auth_runtime_port import (
    AuthRuntimePort,
    IssuedTokenBundlePort,
)
from src.core.auth_contract.token_payload_contract import TokenIssuePayload
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.auth_identity_repository_contract import (
    AuthIdentityRepository,
    AuthIdentitySnapshot,
)
from src.core.persistence_contract.refresh_token_repository_contract import (
    RefreshTokenSessionPayload,
)
from src.domain.auth.auth_error_code import AuthErrorCode

ACCOUNT_DISABLED_MESSAGE = "账号已停用。"
INVALID_CREDENTIAL_MESSAGE = "用户名或密码错误。"


@dataclass(slots=True)
class CredentialInput:
    """
    凭证数据对象，用于承载当前流程的结构化字段。

    :ivar username: 登录用户名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str
    :ivar password_plain: 明文密码。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_plain: str
    """

    username: str
    password_plain: str


class IssueAccessTokenUsecase:
    """
    签发访问令牌应用用例，负责封装当前业务流程。
    """

    def __init__(self, *, runtime_port: AuthRuntimePort) -> None:
        """
        初始化签发访问令牌用例。

        :param runtime_port: 运行时端口实现，用于向用例提供最小依赖能力。约束：需符合 ``IssueAccessTokenRuntimePort`` 注解。
        :type runtime_port: AuthRuntimePort
        :returns: 无返回值。
        :rtype: None
        """

        self._runtime_port = runtime_port

    def execute(self, credential_input: CredentialInput) -> TokenIssuePayload:
        """
        执行签发访问令牌主流程。

        :param credential_input: 令牌签发输入对象，包含用户名和明文密码。约束：需符合 ``CredentialInput`` 注解。
        :type credential_input: CredentialInput
        :returns: 返回当前业务流程产出的结果对象。
        :rtype: TokenIssuePayload
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        :raises Exception: 当底层依赖发生未预期故障时继续向上抛出。
        """

        auth_failure_throttle = self._runtime_port.get_auth_failure_throttle()
        auth_failure_throttle.assert_issue_access_token_allowed(credential_input.username)
        unit_of_work = self._runtime_port.create_unit_of_work()
        try:
            # 同一工作单元内同时完成身份校验、密码升级和刷新令牌会话落库，避免状态撕裂。
            session = unit_of_work.get_session()
            auth_identity_repository = self._runtime_port.create_auth_identity_repository(session)
            refresh_token_repository = self._runtime_port.create_refresh_token_repository(session)
            auth_identity = auth_identity_repository.get_by_username(credential_input.username)
            if auth_identity is None:
                # 用户名不存在时仍然累计失败次数，避免暴露账号枚举侧信道。
                auth_failure_throttle.record_issue_access_token_failure(credential_input.username)
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.INVALID_CREDENTIALS,
                    message=INVALID_CREDENTIAL_MESSAGE,
                )
            if not auth_identity.is_active:
                auth_failure_throttle.record_issue_access_token_failure(credential_input.username)
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.INVALID_CREDENTIALS,
                    message=INVALID_CREDENTIAL_MESSAGE,
                )
            password_hasher = self._runtime_port.get_password_hasher()
            if not password_hasher.verify_password(
                credential_input.password_plain,
                auth_identity.password_hash,
            ):
                # 密码不匹配与用户不存在走同一失败路径，保持外部可观察行为一致。
                auth_failure_throttle.record_issue_access_token_failure(credential_input.username)
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.INVALID_CREDENTIALS,
                    message=INVALID_CREDENTIAL_MESSAGE,
                )
            self._rehash_password_if_needed(
                auth_identity_repository=auth_identity_repository,
                auth_identity=auth_identity,
                password_plain=credential_input.password_plain,
            )
            issued_token_bundle = self._runtime_port.get_jwt_token_service().issue_token_pair(
                auth_identity.to_authenticated_principal()
            )
            refresh_token_repository.create(
                self._build_refresh_token_session_payload(
                    auth_identity.user_id,
                    auth_identity.subject_id,
                    issued_token_bundle,
                )
            )
            # 只有令牌签发与刷新令牌会话同时成功后才提交事务。
            unit_of_work.commit()
            auth_failure_throttle.clear_issue_access_token_failures(credential_input.username)
            return issued_token_bundle.response_payload
        except HttpFaultException:
            # 业务异常也需要回滚，防止密码升级等半途写入。
            unit_of_work.rollback()
            raise
        except Exception:
            # 非预期异常沿原链路继续抛出，但先回滚数据库状态。
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _rehash_password_if_needed(
        self,
        *,
        auth_identity_repository: AuthIdentityRepository,
        auth_identity: AuthIdentitySnapshot,
        password_plain: str,
    ) -> None:
        """
        处理重算哈希密码当所需。

        :param auth_identity_repository: 身份仓储实例。约束：需符合 ``AuthIdentityRepository`` 注解。
        :type auth_identity_repository: AuthIdentityRepository
        :param auth_identity: 当前读取到的身份快照。约束：需符合 ``AuthIdentitySnapshot`` 注解。
        :type auth_identity: AuthIdentitySnapshot
        :param password_plain: 明文密码，仅在当前调用链中短暂使用。约束：需符合 ``str`` 注解。
        :type password_plain: str
        :returns: 无返回值。
        :rtype: None
        """

        password_hasher = self._runtime_port.get_password_hasher()
        if not password_hasher.needs_rehash(auth_identity.password_hash):
            return
        auth_identity_repository.update_password_hash(
            user_id=auth_identity.user_id,
            password_hash=password_hasher.hash_password(password_plain),
        )

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
