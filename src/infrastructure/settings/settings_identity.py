"""Canonical identity for an application settings snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

from pydantic import SecretStr

from src.infrastructure.settings.application_settings import ApplicationSettings

CANDIDATE_VERSION_LENGTH = 12

SettingsSerializableValue = (
    str
    | int
    | float
    | bool
    | list["SettingsSerializableValue"]
    | dict[str, "SettingsSerializableValue"]
    | None
)


@dataclass(frozen=True, slots=True)
class SettingsIdentity:
    """Immutable canonical payload and identifiers for one settings value."""

    canonical_payload: str
    full_digest: str
    candidate_version: str


class SettingsIdentityService:
    """Single canonical serializer used by settings and resource lifecycles."""

    def normalize_settings(
        self, settings: ApplicationSettings
    ) -> dict[str, SettingsSerializableValue]:
        normalized = self._normalize(settings.model_dump(mode="python"))
        if not isinstance(normalized, dict):
            raise TypeError("应用配置规范化结果必须为映射。")
        return normalized

    def identify(self, settings: ApplicationSettings) -> SettingsIdentity:
        normalized = self.normalize_settings(settings)
        canonical_payload = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        full_digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        return SettingsIdentity(
            canonical_payload=canonical_payload,
            full_digest=full_digest,
            candidate_version=full_digest[:CANDIDATE_VERSION_LENGTH],
        )

    def _normalize(self, value: object) -> SettingsSerializableValue:
        if isinstance(value, SecretStr):
            return str(value.get_secret_value())
        if isinstance(value, Enum):
            return self._normalize(value.value)
        if isinstance(value, dict):
            return {str(key): self._normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        raise TypeError(f"配置序列化不支持类型：{type(value).__name__}。")


_DEFAULT_SETTINGS_IDENTITY_SERVICE = SettingsIdentityService()


def identify_settings(settings: ApplicationSettings) -> SettingsIdentity:
    return _DEFAULT_SETTINGS_IDENTITY_SERVICE.identify(settings)


def normalize_settings(settings: ApplicationSettings) -> dict[str, SettingsSerializableValue]:
    """Return the canonical typed payload used by change detection."""

    return _DEFAULT_SETTINGS_IDENTITY_SERVICE.normalize_settings(settings)
