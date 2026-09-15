"""
敏感日志文本脱敏器。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Pattern
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LOG_REDACTION_SCHEMA_VERSION: Final = "1.0"
LOG_REDACTION_RULE_SET_NAME = "default_log_redaction"
CREDENTIAL_URL_REDACTION_KIND: Final = "credential_url_redaction"
BEARER_TOKEN_REDACTION_KIND: Final = "bearer_token_redaction"
KEY_VALUE_SECRET_REDACTION_KIND: Final = "key_value_secret_redaction"
CREDENTIAL_URL_REDACTION_PATTERN = (
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)"
    r"(?P<username>[^/\s:@]+):(?P<password>[^@\s/]+)@"
)
BEARER_TOKEN_REDACTION_PATTERN = r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"
JWT_TEXT_REDACTION_PATTERN = r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
KEY_VALUE_SECRET_REDACTION_PATTERN = (
    r"(?i)\b(?P<key>[A-Za-z0-9_]*(?:PASSWORD|TOKEN|SECRET)"
    r"|(?:api|secret|access|private|public)?_?key|password|passwd|pwd|ticket)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<quote>[\"']?)"
    r"(?P<value>[^\"'\s,;&|]+)"
    r"(?P=quote)"
)
URL_CREDENTIAL_MASK = "***:***@"
SECRET_VALUE_MASK = "***"
BEARER_VALUE_MASK = "Bearer ***"
JWT_VALUE_MASK = "***"


class LogRedactionHeader(BaseModel):
    """
    日志脱敏公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "credential_url_redaction",
        "bearer_token_redaction",
        "key_value_secret_redaction",
    ]
    schema_version: Literal["1.0"] = LOG_REDACTION_SCHEMA_VERSION
    rule_set_name: str = LOG_REDACTION_RULE_SET_NAME


class CredentialUrlRedactionDetail(BaseModel):
    """
    凭据 URL 脱敏扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["credential_url_redaction"] = CREDENTIAL_URL_REDACTION_KIND
    schema_version: Literal["1.0"] = LOG_REDACTION_SCHEMA_VERSION
    pattern_name: str = "url_user_password"


class BearerTokenRedactionDetail(BaseModel):
    """
    Bearer Token 脱敏扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["bearer_token_redaction"] = BEARER_TOKEN_REDACTION_KIND
    schema_version: Literal["1.0"] = LOG_REDACTION_SCHEMA_VERSION
    pattern_name: str = "bearer_and_jwt"


class KeyValueSecretRedactionDetail(BaseModel):
    """
    键值密钥脱敏扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["key_value_secret_redaction"] = KEY_VALUE_SECRET_REDACTION_KIND
    schema_version: Literal["1.0"] = LOG_REDACTION_SCHEMA_VERSION
    pattern_name: str = "key_value_secret"


LogRedactionRuleDetail = Annotated[
    CredentialUrlRedactionDetail | BearerTokenRedactionDetail | KeyValueSecretRedactionDetail,
    Field(discriminator="kind"),
]


class LogRedactionRuleEnvelope(BaseModel):
    """
    日志脱敏规则信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: LogRedactionHeader
    detail: LogRedactionRuleDetail

    @model_validator(mode="after")
    def validate_redaction_contract(self) -> LogRedactionRuleEnvelope:
        """
        校验日志脱敏规则公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("日志脱敏 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("日志脱敏 header.schema_version 必须与 detail.schema_version 一致。")
        return self


@dataclass(slots=True)
class SensitiveTextRedactor:
    """
    敏感文本脱敏器。
    """

    credential_url_pattern: Pattern[str] = field(
        default_factory=lambda: re.compile(CREDENTIAL_URL_REDACTION_PATTERN)
    )
    bearer_token_pattern: Pattern[str] = field(
        default_factory=lambda: re.compile(BEARER_TOKEN_REDACTION_PATTERN)
    )
    jwt_text_pattern: Pattern[str] = field(
        default_factory=lambda: re.compile(JWT_TEXT_REDACTION_PATTERN)
    )
    key_value_secret_pattern: Pattern[str] = field(
        default_factory=lambda: re.compile(KEY_VALUE_SECRET_REDACTION_PATTERN)
    )

    def build_rule_envelopes(self) -> list[LogRedactionRuleEnvelope]:
        """
        构建脱敏规则信封集合。
        """

        return [
            LogRedactionRuleEnvelope(
                header=LogRedactionHeader(kind=CREDENTIAL_URL_REDACTION_KIND),
                detail=CredentialUrlRedactionDetail(),
            ),
            LogRedactionRuleEnvelope(
                header=LogRedactionHeader(kind=BEARER_TOKEN_REDACTION_KIND),
                detail=BearerTokenRedactionDetail(),
            ),
            LogRedactionRuleEnvelope(
                header=LogRedactionHeader(kind=KEY_VALUE_SECRET_REDACTION_KIND),
                detail=KeyValueSecretRedactionDetail(),
            ),
        ]

    def redact(self, text: str | None) -> str | None:
        """
        脱敏敏感文本。

        :param text: 原始文本。
        :type text: str | None
        :returns: 脱敏后的文本。
        :rtype: str | None
        """

        if text is None:
            return None
        redacted_text = self.credential_url_pattern.sub(
            self._replace_credential_url,
            text,
        )
        redacted_text = self.bearer_token_pattern.sub(
            BEARER_VALUE_MASK,
            redacted_text,
        )
        redacted_text = self.jwt_text_pattern.sub(JWT_VALUE_MASK, redacted_text)
        return self.key_value_secret_pattern.sub(
            self._replace_key_value_secret,
            redacted_text,
        )

    def _replace_credential_url(self, match: re.Match[str]) -> str:
        """
        替换 URL 凭据。
        """

        return f"{match.group('scheme')}{URL_CREDENTIAL_MASK}"

    def _replace_key_value_secret(self, match: re.Match[str]) -> str:
        """
        替换键值密钥。
        """

        quote = match.group("quote")
        return f"{match.group('key')}{match.group('separator')}{quote}{SECRET_VALUE_MASK}{quote}"
