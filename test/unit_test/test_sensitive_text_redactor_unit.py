"""
敏感文本脱敏单元测试。
"""

from __future__ import annotations

from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor

DATABASE_URL_TEXT = "postgresql+psycopg://user:secret-password@db:5432/app"
BEARER_TOKEN_TEXT = "Bearer abcdefghijklmnopqrstuvwxyz0123456789"
JWT_TEXT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturelong"
PASSWORD_TEXT = "password=plain-secret"
ENV_PASSWORD_TEXT = "AUTH_BOOTSTRAP_ADMIN_PASSWORD=admin-secret"
API_KEY_TEXT = "api_key=plain-key-value"
BUSINESS_TEXT = "普通业务文本不包含敏感键值。"
SECRET_MASK = "***"


class TestSensitiveTextRedactorUnit:
    """
    敏感文本脱敏单元测试集合。
    """

    def test_redact_when_database_url_contains_credential_should_mask_password(self) -> None:
        """
        验证数据库 URL 凭据应被脱敏。
        """

        redacted = SensitiveTextRedactor().redact(DATABASE_URL_TEXT)

        assert redacted == "postgresql+psycopg://***:***@db:5432/app"
        assert "secret-password" not in redacted

    def test_redact_when_bearer_token_exists_should_mask_token(self) -> None:
        """
        验证 Bearer Token 应被脱敏。
        """

        redacted = SensitiveTextRedactor().redact(BEARER_TOKEN_TEXT)

        assert redacted == "Bearer ***"

    def test_redact_when_jwt_text_exists_should_mask_jwt(self) -> None:
        """
        验证 JWT 文本应被脱敏。
        """

        redacted = SensitiveTextRedactor().redact(JWT_TEXT)

        assert redacted == SECRET_MASK

    def test_redact_when_password_key_value_exists_should_mask_value(self) -> None:
        """
        验证 password 键值应被脱敏。
        """

        redacted = SensitiveTextRedactor().redact(PASSWORD_TEXT)

        assert redacted == "password=***"

    def test_redact_when_environment_password_exists_should_mask_value(self) -> None:
        """
        验证环境变量密码键值应被脱敏。
        """

        redacted = SensitiveTextRedactor().redact(ENV_PASSWORD_TEXT)

        assert redacted == "AUTH_BOOTSTRAP_ADMIN_PASSWORD=***"

    def test_redact_when_api_key_exists_should_mask_value(self) -> None:
        """
        验证 API key 键值应被脱敏。
        """

        redacted = SensitiveTextRedactor().redact(API_KEY_TEXT)

        assert redacted == "api_key=***"

    def test_redact_when_business_text_has_no_secret_should_keep_text(self) -> None:
        """
        验证普通业务文本不应被误删。
        """

        redacted = SensitiveTextRedactor().redact(BUSINESS_TEXT)

        assert redacted == BUSINESS_TEXT
