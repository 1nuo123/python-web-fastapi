"""
外部 HTTP 客户端契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.http_contract.outbound_http_client_contract import (
    DEFAULT_OUTBOUND_HTTP_CLIENT_NAME,
    OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND,
    AsyncHttpClientDetail,
    OutboundHttpClientEnvelope,
    OutboundHttpClientHeader,
    OutboundHttpClientMode,
    SyncHttpClientDetail,
)


class TestOutboundHttpClientContract:
    """
    外部 HTTP 客户端契约测试集合。
    """

    def test_envelope_when_async_detail_should_keep_header_and_extension(self) -> None:
        """
        验证外部 HTTP 客户端信封在异步模式下应保持头与扩展一致。
        """

        envelope = OutboundHttpClientEnvelope(
            envelope_kind=OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND,
            schema_version="1.0",
            header=OutboundHttpClientHeader(
                client_name=DEFAULT_OUTBOUND_HTTP_CLIENT_NAME,
                enabled=True,
                mode=OutboundHttpClientMode.ASYNC_HTTP,
            ),
            detail=AsyncHttpClientDetail(
                timeout_seconds=5,
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )

        assert envelope.header.mode == OutboundHttpClientMode.ASYNC_HTTP
        assert envelope.detail.kind == "async_http"

    def test_envelope_when_mode_and_kind_mismatch_should_fail(self) -> None:
        """
        验证外部 HTTP 客户端信封当外层模式与内层类型不一致应失败。
        """

        with pytest.raises(ValidationError) as exc_info:
            OutboundHttpClientEnvelope(
                envelope_kind=OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND,
                schema_version="1.0",
                header=OutboundHttpClientHeader(
                    client_name=DEFAULT_OUTBOUND_HTTP_CLIENT_NAME,
                    enabled=True,
                    mode=OutboundHttpClientMode.ASYNC_HTTP,
                ),
                detail=SyncHttpClientDetail(
                    timeout_seconds=5,
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )

        assert "mode 与 detail.kind 不一致" in str(exc_info.value)

    def test_detail_when_unknown_field_should_forbid_extra(self) -> None:
        """
        验证外部 HTTP 客户端扩展体应禁止额外字段。
        """

        with pytest.raises(ValidationError):
            AsyncHttpClientDetail(
                kind="async_http",
                schema_version="1.0",
                timeout_seconds=5,
                max_connections=10,
                max_keepalive_connections=5,
                unexpected_field=True,
            )
