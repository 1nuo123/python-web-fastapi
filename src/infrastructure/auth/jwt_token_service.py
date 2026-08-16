"""
JWT令牌服务基础设施模块。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus

import jwt
from pydantic import ValidationError

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import (
    TOKEN_BEARER_TYPE,
    TOKEN_PAYLOAD_KIND,
    TOKEN_SCHEMA_VERSION,
    TokenIssuePayload,
    TokenPayload,
    TokenUse,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.key_management.key_management_service import (
    KeyManagementKeyIdNotFoundError,
    KeyManagementService,
)

JWT_TOKEN_ID_CLAIM = "jti"
JWT_TOKEN_SESSION_ID_CLAIM = "sid"
JWT_SUBJECT_ID_CLAIM = "sub"
JWT_USERNAME_CLAIM = "username"
JWT_ROLES_CLAIM = "roles"
JWT_SCOPES_CLAIM = "scopes"
JWT_TOKEN_USE_CLAIM = "token_use"
JWT_ISSUED_AT_CLAIM = "iat"
JWT_EXPIRES_AT_CLAIM = "exp"
JWT_ISSUER_CLAIM = "iss"
JWT_AUDIENCE_CLAIM = "aud"
JWT_KIND_CLAIM = "kind"
JWT_SCHEMA_VERSION_CLAIM = "schema_version"
JWT_KEY_ID_HEADER = "kid"
JWT_SIGNING_KEY_FAMILY = "jwt_signing"


@dataclass(slots=True)
class IssuedTokenBundle:
    """
    已签发令牌集合数据对象，用于承载当前流程的结构化字段。

    :ivar response_payload: ``response_payload`` 字段。约束：需符合 ``TokenIssuePayload`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype response_payload: TokenIssuePayload
    :ivar access_token_payload: ``access_token_payload`` 字段。约束：需符合 ``TokenPayload`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype access_token_payload: TokenPayload
    :ivar refresh_token_payload: ``refresh_token_payload`` 字段。约束：需符合 ``TokenPayload`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token_payload: TokenPayload
    """

    response_payload: TokenIssuePayload
    access_token_payload: TokenPayload
    refresh_token_payload: TokenPayload


class JwtTokenService:
    """
    JWT令牌服务，负责提供可复用的领域或基础设施能力。
    """

    def __init__(
        self,
        policy: AccessTokenPolicy,
        *,
        key_management_service: KeyManagementService | None = None,
        key_family_name: str = JWT_SIGNING_KEY_FAMILY,
    ) -> None:
        """
        初始化JWT令牌服务。

        :param policy: 授权策略对象。约束：需符合 ``AccessTokenPolicy`` 注解。
        :type policy: AccessTokenPolicy
        :returns: 无返回值。
        :rtype: None
        """

        self._policy = policy
        self._key_management_service = key_management_service
        self._key_family_name = key_family_name

    def issue_token_pair(
        self,
        principal: AuthenticatedPrincipal,
        *,
        current_epoch: int | None = None,
        token_session_id: uuid.UUID | None = None,
    ) -> IssuedTokenBundle:
        """
        签发令牌成对。

        :param principal: 认证主体对象。约束：需符合 ``AuthenticatedPrincipal`` 注解。
        :type principal: AuthenticatedPrincipal
        :param current_epoch: 当前 Unix 时间戳秒值。默认值：`None`。约束：需符合 ``int | None`` 注解。
        :type current_epoch: int | None
        :param token_session_id: 令牌会话标识，用于串联一组访问令牌与刷新令牌。默认值：`None`。约束：需符合 ``str | None`` 注解。
        :type token_session_id: str | None
        :returns: 返回当前操作结果。
        :rtype: IssuedTokenBundle
        """

        now_epoch = current_epoch or int(time.time())
        resolved_token_session_id = token_session_id or uuid.uuid4()
        access_payload = self._build_payload(
            principal=principal,
            token_use=TokenUse.ACCESS,
            current_epoch=now_epoch,
            expires_in_seconds=self._policy.access_token_expires_in_seconds,
            token_session_id=resolved_token_session_id,
        )
        refresh_payload = self._build_payload(
            principal=principal,
            token_use=TokenUse.REFRESH,
            current_epoch=now_epoch,
            expires_in_seconds=self._policy.refresh_token_expires_in_seconds,
            token_session_id=resolved_token_session_id,
        )
        return IssuedTokenBundle(
            response_payload=TokenIssuePayload(
                access_token=self._encode_payload(access_payload),
                refresh_token=self._encode_payload(refresh_payload),
                token_type=TOKEN_BEARER_TYPE,
                expires_in_seconds=self._policy.access_token_expires_in_seconds,
                refresh_expires_in_seconds=self._policy.refresh_token_expires_in_seconds,
            ),
            access_token_payload=access_payload,
            refresh_token_payload=refresh_payload,
        )

    def decode_token(
        self,
        token: str,
        *,
        expected_use: TokenUse,
        current_epoch: int | None = None,
    ) -> TokenPayload:
        """
        解码令牌。

        :param token: 当前步骤使用的令牌参数。约束：需符合 ``str`` 注解。
        :type token: str
        :param expected_use: 令牌用途的预期值。约束：需符合 ``TokenUse`` 注解。
        :type expected_use: TokenUse
        :param current_epoch: 当前 Unix 时间戳秒值。默认值：`None`。约束：需符合 ``int | None`` 注解。
        :type current_epoch: int | None
        :returns: 返回当前操作结果。
        :rtype: TokenPayload
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        try:
            raw_payload = self._decode_raw_payload(token)
        except jwt.InvalidTokenError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_INVALID,
                message="令牌无效。",
                detail=str(exc),
            ) from exc
        try:
            token_payload = TokenPayload.model_validate(
                {
                    "kind": raw_payload[JWT_KIND_CLAIM],
                    "schema_version": raw_payload[JWT_SCHEMA_VERSION_CLAIM],
                    "token_id": raw_payload[JWT_TOKEN_ID_CLAIM],
                    "token_session_id": raw_payload[JWT_TOKEN_SESSION_ID_CLAIM],
                    "subject_id": raw_payload[JWT_SUBJECT_ID_CLAIM],
                    "username": raw_payload[JWT_USERNAME_CLAIM],
                    "roles": raw_payload[JWT_ROLES_CLAIM],
                    "scopes": raw_payload[JWT_SCOPES_CLAIM],
                    "token_use": raw_payload[JWT_TOKEN_USE_CLAIM],
                    "issued_at_epoch": raw_payload[JWT_ISSUED_AT_CLAIM],
                    "expires_at_epoch": raw_payload[JWT_EXPIRES_AT_CLAIM],
                }
            )
        except (KeyError, ValidationError) as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_INVALID,
                message="令牌载荷不完整。",
                detail=str(exc),
            ) from exc
        self._validate_payload(
            token_payload, expected_use=expected_use, current_epoch=current_epoch
        )
        return token_payload

    def _build_payload(
        self,
        *,
        principal: AuthenticatedPrincipal,
        token_use: TokenUse,
        current_epoch: int,
        expires_in_seconds: int,
        token_session_id: uuid.UUID,
    ) -> TokenPayload:
        """
        构建载荷。

        :param principal: 认证主体对象。约束：需符合 ``AuthenticatedPrincipal`` 注解。
        :type principal: AuthenticatedPrincipal
        :param token_use: 当前步骤使用的令牌用途参数。约束：需符合 ``TokenUse`` 注解。
        :type token_use: TokenUse
        :param current_epoch: 当前 Unix 时间戳秒值。约束：需符合 ``int`` 注解。
        :type current_epoch: int
        :param expires_in_seconds: 当前步骤使用的expiresin秒数参数。约束：需符合 ``int`` 注解。
        :type expires_in_seconds: int
        :param token_session_id: 令牌会话标识，用于串联一组访问令牌与刷新令牌。
        :type token_session_id: uuid.UUID
        :returns: 返回当前操作结果。
        :rtype: TokenPayload
        """

        return TokenPayload(
            kind=TOKEN_PAYLOAD_KIND,
            schema_version=TOKEN_SCHEMA_VERSION,
            token_id=uuid.uuid4(),
            token_session_id=token_session_id,
            subject_id=principal.subject_id,
            username=principal.username,
            roles=principal.roles,
            scopes=principal.scopes,
            token_use=token_use,
            issued_at_epoch=current_epoch,
            expires_at_epoch=current_epoch + expires_in_seconds,
        )

    def _encode_payload(self, payload: TokenPayload) -> str:
        """
        编码载荷。

        :param payload: 结构化载荷对象。约束：需符合 ``TokenPayload`` 注解。
        :type payload: TokenPayload
        :returns: 返回当前操作结果。
        :rtype: str
        """

        signing_key = self._read_signing_key_material()
        token_headers = (
            {JWT_KEY_ID_HEADER: self._read_current_key_id()}
            if self._key_management_service is not None
            else None
        )
        return jwt.encode(
            {
                JWT_KIND_CLAIM: payload.kind,
                JWT_SCHEMA_VERSION_CLAIM: payload.schema_version,
                JWT_TOKEN_ID_CLAIM: str(payload.token_id),
                JWT_TOKEN_SESSION_ID_CLAIM: str(payload.token_session_id),
                JWT_SUBJECT_ID_CLAIM: payload.subject_id,
                JWT_USERNAME_CLAIM: payload.username,
                JWT_ROLES_CLAIM: payload.roles,
                JWT_SCOPES_CLAIM: payload.scopes,
                JWT_TOKEN_USE_CLAIM: payload.token_use,
                JWT_ISSUED_AT_CLAIM: payload.issued_at_epoch,
                JWT_EXPIRES_AT_CLAIM: payload.expires_at_epoch,
                JWT_ISSUER_CLAIM: self._policy.issuer,
                JWT_AUDIENCE_CLAIM: self._policy.audience,
            },
            signing_key,
            algorithm=self._policy.jwt_algorithm,
            headers=token_headers,
        )

    def _decode_raw_payload(self, token: str) -> dict[str, object]:
        """
        解码 JWT 原始载荷。
        """

        return jwt.decode(
            token,
            self._read_verification_key_material(token),
            algorithms=[self._policy.jwt_algorithm],
            audience=self._policy.audience,
            issuer=self._policy.issuer,
            options={"verify_exp": False},
        )

    def _read_signing_key_material(self) -> str:
        """
        读取当前 JWT 签名密钥材料。
        """

        if self._key_management_service is None:
            return self._policy.jwt_secret
        return self._key_management_service.get_current_key(self._key_family_name).key_material

    def _read_current_key_id(self) -> str:
        """
        读取当前 JWT 签名 key id。
        """

        if self._key_management_service is None:
            return ""
        return self._key_management_service.get_current_key(self._key_family_name).key_id

    def _read_verification_key_material(self, token: str) -> str:
        """
        读取 JWT 验签密钥材料。
        """

        if self._key_management_service is None:
            return self._policy.jwt_secret
        headers = jwt.get_unverified_header(token)
        key_id = headers.get(JWT_KEY_ID_HEADER)
        if not isinstance(key_id, str) or key_id.strip() == "":
            raise jwt.InvalidTokenError("JWT 缺少 key id。")
        try:
            return self._key_management_service.get_key_by_id(
                self._key_family_name,
                key_id,
            ).key_material
        except KeyManagementKeyIdNotFoundError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_INVALID,
                message="令牌无效。",
                detail=exc.detail,
            ) from exc

    def _validate_payload(
        self,
        token_payload: TokenPayload,
        *,
        expected_use: TokenUse,
        current_epoch: int | None,
    ) -> None:
        """
        校验载荷。

        :param token_payload: 已解码并完成基础校验的令牌载荷。约束：需符合 ``TokenPayload`` 注解。
        :type token_payload: TokenPayload
        :param expected_use: 令牌用途的预期值。约束：需符合 ``TokenUse`` 注解。
        :type expected_use: TokenUse
        :param current_epoch: 当前 Unix 时间戳秒值。约束：需符合 ``int | None`` 注解。
        :type current_epoch: int | None
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        now_epoch = current_epoch or int(time.time())
        if token_payload.token_use != expected_use:
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_INVALID,
                message="令牌用途不匹配。",
            )
        if now_epoch >= token_payload.expires_at_epoch:
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_EXPIRED,
                message="令牌已过期。",
            )
