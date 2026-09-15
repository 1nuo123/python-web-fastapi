"""Credential redaction for Uvicorn HTTP and WebSocket access logging."""

from __future__ import annotations

import logging
from copy import deepcopy

from uvicorn.config import LOGGING_CONFIG

from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor


class WebServerCredentialFilter(logging.Filter):
    """Retain Uvicorn's positional access arguments while masking credentials."""

    def __init__(self) -> None:
        super().__init__()
        self._redactor = SensitiveTextRedactor()

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redactor.redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._redactor.redact(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: self._redactor.redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def build_web_server_log_config() -> dict[str, object]:
    """Use the server's native handlers with one shared credential filter."""

    config = deepcopy(LOGGING_CONFIG)
    config["filters"] = {"credentials": {"()": WebServerCredentialFilter}}
    for handler in config["handlers"].values():
        handler["filters"] = ["credentials"]
    return config
