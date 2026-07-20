"""
出站 URL 安全契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OUTBOUND_URL_SAFETY_SCHEMA_VERSION: Final = "1.0"
OUTBOUND_URL_SAFETY_KIND: Final = "outbound_url_safety"
OUTBOUND_URL_SAFETY_DECISION_KIND: Final = "outbound_url_safety_decision"
OUTBOUND_URL_SAFETY_EVENT_TYPE = "ssrf.blocked"
OUTBOUND_URL_SAFETY_DEFAULT_SENTINEL_HOST_DIGEST = "host-unavailable"
OUTBOUND_URL_SAFETY_EMPTY_TEXT = ""
OUTBOUND_URL_SAFETY_ALLOWED_HOSTNAME_BLANK_MESSAGE = (
    "outbound_url_safety.allowed_hostnames 不允许包含空白值。"
)
OUTBOUND_URL_SAFETY_DENY_HOSTNAME_BLANK_MESSAGE = (
    "outbound_url_safety.deny_hostnames 不允许包含空白值。"
)


class OutboundUrlSafetyAction(StrEnum):
    """
    出站 URL 安全动作。
    """

    ALLOW = "allow"
    DENY = "deny"


class OutboundUrlSafetyEnvelope(BaseModel):
    """
    出站 URL 安全策略信封。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["outbound_url_safety"] = OUTBOUND_URL_SAFETY_KIND
    schema_version: Literal["1.0"] = OUTBOUND_URL_SAFETY_SCHEMA_VERSION
    enabled: bool
    allowed_schemes: list[str]
    deny_private_networks: bool
    deny_metadata_address: bool
    deny_cidr_blocks: list[str] = Field(default_factory=list)
    deny_hostnames: list[str] = Field(default_factory=list)
    allowed_hostnames: list[str] = Field(default_factory=list)
    enforce_allowed_hostnames: bool = False

    @model_validator(mode="after")
    def validate_hostname_collections(self) -> OutboundUrlSafetyEnvelope:
        """
        校验并归一化出站主机清单。

        :returns: 当前策略信封。
        :rtype: OutboundUrlSafetyEnvelope
        :raises ValueError: 当主机清单包含空白值时抛出。
        """

        self.allowed_hostnames = self._normalize_hostnames(
            hostnames=self.allowed_hostnames,
            blank_message=OUTBOUND_URL_SAFETY_ALLOWED_HOSTNAME_BLANK_MESSAGE,
        )
        self.deny_hostnames = self._normalize_hostnames(
            hostnames=self.deny_hostnames,
            blank_message=OUTBOUND_URL_SAFETY_DENY_HOSTNAME_BLANK_MESSAGE,
        )
        return self

    def _normalize_hostnames(
        self,
        *,
        hostnames: list[str],
        blank_message: str,
    ) -> list[str]:
        """
        归一化主机名清单。

        :param hostnames: 待归一化的主机名清单。
        :type hostnames: list[str]
        :param blank_message: 空白值错误信息。
        :type blank_message: str
        :returns: 小写且去除首尾空白的主机名清单。
        :rtype: list[str]
        :raises ValueError: 当清单包含空白值时抛出。
        """

        normalized_hostnames: list[str] = []
        for hostname in hostnames:
            normalized_hostname = hostname.strip().lower()
            if normalized_hostname == OUTBOUND_URL_SAFETY_EMPTY_TEXT:
                raise ValueError(blank_message)
            normalized_hostnames.append(normalized_hostname)
        return normalized_hostnames


class OutboundUrlSafetyDecision(BaseModel):
    """
    出站 URL 安全决策。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["outbound_url_safety_decision"] = OUTBOUND_URL_SAFETY_DECISION_KIND
    schema_version: Literal["1.0"] = OUTBOUND_URL_SAFETY_SCHEMA_VERSION
    action: OutboundUrlSafetyAction
    reason_code: str
    event_type: str | None = None
    host_digest: str = OUTBOUND_URL_SAFETY_DEFAULT_SENTINEL_HOST_DIGEST
    resolved_address: str | None = None
