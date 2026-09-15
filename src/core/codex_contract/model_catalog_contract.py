"""Bounded model capabilities observed from the current App Server instance."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CodexModelCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    reasoning_efforts: tuple[str, ...] = Field(default=(), max_length=16)
    default_reasoning_effort: str | None = Field(default=None, max_length=64)
    is_default: bool = False


class CodexEffectiveExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, max_length=128)
    model_provider: str = Field(min_length=1, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=64)


class CodexModelCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["unknown", "ready", "unavailable"] = "unknown"
    models: tuple[CodexModelCapability, ...] = Field(default=(), max_length=512)

    def resolve(self, model: str | None) -> CodexModelCapability | None:
        return next((item for item in self.models if item.model == model), None) if model else next(
            (item for item in self.models if item.is_default), None
        )
