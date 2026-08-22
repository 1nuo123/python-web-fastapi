"""Turn 客户端操作身份的 HTTP 与 Agent 边界契约。"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

import pytest

from src.api.endpoint_codex_control.route_codex_thread import (
    _validate_turn_operation_identity,
)
from src.core.codex_contract.turn_contract import CodexTurnStartRequest
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


def test_turn_request_when_header_matches_client_operation_id_should_be_accepted() -> None:
    """HTTP 重试头与请求体使用同一 UUID 时允许进入幂等账本。"""

    client_operation_id = UUID("11111111-1111-4111-8111-111111111111")
    request = CodexTurnStartRequest(
        client_operation_id=client_operation_id,
        message="继续",
    )

    _validate_turn_operation_identity(request, str(client_operation_id))


def test_turn_request_when_header_differs_should_reject_before_side_effect() -> None:
    """不一致身份不能创建 operation、outbox 或上游 turn。"""

    request = CodexTurnStartRequest(
        client_operation_id=UUID("11111111-1111-4111-8111-111111111111"),
        message="继续",
    )

    with pytest.raises(HttpFaultException) as exception_info:
        _validate_turn_operation_identity(
            request,
            "22222222-2222-4222-8222-222222222222",
        )

    error = exception_info.value
    assert error.status_code == HTTPStatus.BAD_REQUEST
    assert error.error_code == CodexErrorCode.IDEMPOTENCY_KEY_MISMATCH
