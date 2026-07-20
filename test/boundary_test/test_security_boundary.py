"""
安全边界测试模块。
"""

from __future__ import annotations

import jwt
import pytest
from pydantic import ValidationError

from src.core.auth_contract.token_payload_contract import (
    TOKEN_PAYLOAD_KIND,
    TOKEN_SCHEMA_VERSION,
    TokenUse,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.security_runtime_contract import (
    DevelopmentSecurityRuntimeDetail,
    ProductionSecurityRuntimeDetail,
    SecurityRuntimeEnvelope,
    SecurityRuntimeHeader,
    SecurityRuntimeMode,
)
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.auth.jwt_token_service import (
    JWT_AUDIENCE_CLAIM,
    JWT_EXPIRES_AT_CLAIM,
    JWT_ISSUED_AT_CLAIM,
    JWT_ISSUER_CLAIM,
    JWT_KIND_CLAIM,
    JWT_ROLES_CLAIM,
    JWT_SCHEMA_VERSION_CLAIM,
    JWT_SCOPES_CLAIM,
    JWT_SUBJECT_ID_CLAIM,
    JWT_TOKEN_ID_CLAIM,
    JWT_TOKEN_SESSION_ID_CLAIM,
    JWT_TOKEN_USE_CLAIM,
    JWT_USERNAME_CLAIM,
    JwtTokenService,
)
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)

JWT_TEST_SECRET = "security-boundary-secret-2026-with-safe-length"
JWT_TEST_ALGORITHM = "HS256"
JWT_TEST_ISSUER = "security-boundary"
JWT_TEST_AUDIENCE = "security-client"
JWT_TEST_CURRENT_EPOCH = 100
JWT_TEST_EXPIRES_AT_EPOCH = 200
INVALID_UUID_VALUE = "not-a-uuid"
VALID_UUID_VALUE = "11111111-1111-4111-8111-111111111111"


class TestSecurityBoundary:
    """
    安全边界测试集合。
    """

    def test_loader_when_production_jwt_short_should_fail(self, monkeypatch) -> None:
        """
        验证生产短密钥应失败。
        """

        monkeypatch.setenv("JWT_SECRET", "short-secret")

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "弱密钥" in str(fault.value)

    def test_loader_when_production_jwt_contains_dev_secret_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产密钥包含开发示例片段时应失败。
        """

        monkeypatch.setenv(
            "JWT_SECRET",
            "prefix-dev-secret-with-safe-length-suffix",
        )

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "弱密钥" in str(fault.value)

    def test_security_detail_when_extra_field_should_fail(self) -> None:
        """
        验证安全扩展字段出现未声明字段时应失败。
        """

        with pytest.raises(ValidationError) as fault:
            ProductionSecurityRuntimeDetail.model_validate(
                {
                    "kind": "production_security",
                    "schema_version": "1.0",
                    "expose_openapi": False,
                    "expose_system_info": False,
                    "require_external_jwt_secret": True,
                    "require_distributed_auth_throttle": True,
                    "enable_hsts": True,
                    "enable_csp": True,
                    "extra_payload": {},
                }
            )

        assert "extra_payload" in str(fault.value)

    def test_security_envelope_when_outer_inner_type_mismatch_should_fail(self) -> None:
        """
        验证外层安全模式与内层扩展类型不一致时应失败。
        """

        with pytest.raises(ValidationError) as fault:
            SecurityRuntimeEnvelope(
                header=SecurityRuntimeHeader(
                    mode=SecurityRuntimeMode.PRODUCTION,
                    enabled=True,
                    policy_name="production_public_baseline",
                ),
                detail=DevelopmentSecurityRuntimeDetail(
                    expose_openapi=True,
                    expose_system_info=False,
                    require_external_jwt_secret=False,
                    require_distributed_auth_throttle=False,
                    enable_hsts=False,
                    enable_csp=False,
                ),
            )

        assert "mode 必须与 detail.kind 一致" in str(fault.value)

    def test_jwt_payload_when_jti_is_not_uuid_should_return_token_invalid(self) -> None:
        """
        验证合法签名但非法 jti 应返回稳定令牌无效错误。

        :returns: 无返回值。
        :rtype: None
        """

        token_service = self._build_jwt_token_service()
        token = self._build_signed_token(
            token_id=INVALID_UUID_VALUE,
            token_session_id=VALID_UUID_VALUE,
        )

        with pytest.raises(HttpFaultException) as fault:
            token_service.decode_token(
                token,
                expected_use=TokenUse.ACCESS,
                current_epoch=JWT_TEST_CURRENT_EPOCH,
            )

        assert fault.value.status_code == 401
        assert fault.value.error_code == str(AuthErrorCode.TOKEN_INVALID)

    def test_jwt_payload_when_sid_is_not_uuid_should_return_token_invalid(self) -> None:
        """
        验证合法签名但非法 sid 应返回稳定令牌无效错误。

        :returns: 无返回值。
        :rtype: None
        """

        token_service = self._build_jwt_token_service()
        token = self._build_signed_token(
            token_id=VALID_UUID_VALUE,
            token_session_id=INVALID_UUID_VALUE,
        )

        with pytest.raises(HttpFaultException) as fault:
            token_service.decode_token(
                token,
                expected_use=TokenUse.ACCESS,
                current_epoch=JWT_TEST_CURRENT_EPOCH,
            )

        assert fault.value.status_code == 401
        assert fault.value.error_code == str(AuthErrorCode.TOKEN_INVALID)

    def _build_jwt_token_service(self) -> JwtTokenService:
        """
        构建 JWT 令牌服务。

        :returns: JWT 令牌服务。
        :rtype: JwtTokenService
        """

        return JwtTokenService(
            AccessTokenPolicy(
                jwt_secret=JWT_TEST_SECRET,
                jwt_algorithm=JWT_TEST_ALGORITHM,
                access_token_expires_in_seconds=60,
                refresh_token_expires_in_seconds=120,
                issuer=JWT_TEST_ISSUER,
                audience=JWT_TEST_AUDIENCE,
                refresh_token_rotation_enabled=True,
            )
        )

    def _build_signed_token(self, *, token_id: str, token_session_id: str) -> str:
        """
        构建带指定 jti 和 sid 的签名令牌。

        :param token_id: 令牌标识。
        :type token_id: str
        :param token_session_id: 令牌会话标识。
        :type token_session_id: str
        :returns: 签名 JWT。
        :rtype: str
        """

        return jwt.encode(
            {
                JWT_KIND_CLAIM: TOKEN_PAYLOAD_KIND,
                JWT_SCHEMA_VERSION_CLAIM: TOKEN_SCHEMA_VERSION,
                JWT_TOKEN_ID_CLAIM: token_id,
                JWT_TOKEN_SESSION_ID_CLAIM: token_session_id,
                JWT_SUBJECT_ID_CLAIM: "user-admin",
                JWT_USERNAME_CLAIM: "admin",
                JWT_ROLES_CLAIM: ["admin"],
                JWT_SCOPES_CLAIM: ["auth:read"],
                JWT_TOKEN_USE_CLAIM: TokenUse.ACCESS,
                JWT_ISSUED_AT_CLAIM: JWT_TEST_CURRENT_EPOCH,
                JWT_EXPIRES_AT_CLAIM: JWT_TEST_EXPIRES_AT_EPOCH,
                JWT_ISSUER_CLAIM: JWT_TEST_ISSUER,
                JWT_AUDIENCE_CLAIM: JWT_TEST_AUDIENCE,
            },
            JWT_TEST_SECRET,
            algorithm=JWT_TEST_ALGORITHM,
        )
