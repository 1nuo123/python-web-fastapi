"""
刷新令牌失效契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.auth_contract.refresh_token_invalidation_contract import (
    AllRefreshTokenSessionsDetail,
    RefreshTokenInvalidationCommand,
    RefreshTokenInvalidationHeader,
    RefreshTokenInvalidationMode,
    SubjectRefreshTokenSessionsDetail,
    TokenSessionInvalidationDetail,
)

TOKEN_SESSION_ID_VALUE = "session-1"
UNEXPECTED_FIELD_ERROR_FRAGMENT = "Extra inputs are not permitted"


class TestRefreshTokenInvalidationContract:
    """
    刷新令牌失效契约测试集合。
    """

    def test_command_when_all_detail_should_keep_mode_consistent(self) -> None:
        """
        验证全量失效命令应保持公共头与扩展字段一致。
        """

        command = RefreshTokenInvalidationCommand(
            header=RefreshTokenInvalidationHeader(
                mode=RefreshTokenInvalidationMode.ALL,
            ),
            detail=AllRefreshTokenSessionsDetail(),
        )

        assert command.header.mode == RefreshTokenInvalidationMode.ALL
        assert command.detail.kind == RefreshTokenInvalidationMode.ALL.value

    def test_command_when_token_session_detail_should_keep_mode_consistent(self) -> None:
        """
        验证指定令牌会话失效命令应保持公共头与扩展字段一致。
        """

        command = RefreshTokenInvalidationCommand(
            header=RefreshTokenInvalidationHeader(
                mode=RefreshTokenInvalidationMode.TOKEN_SESSION,
            ),
            detail=TokenSessionInvalidationDetail(
                token_session_id=TOKEN_SESSION_ID_VALUE,
            ),
        )

        assert command.header.mode == RefreshTokenInvalidationMode.TOKEN_SESSION
        assert command.detail.kind == RefreshTokenInvalidationMode.TOKEN_SESSION.value
        assert command.detail.token_session_id == TOKEN_SESSION_ID_VALUE

    def test_command_when_header_detail_mismatch_should_fail(self) -> None:
        """
        验证失效模式与扩展类型不一致时应失败。
        """

        with pytest.raises(ValidationError) as fault:
            RefreshTokenInvalidationCommand(
                header=RefreshTokenInvalidationHeader(
                    mode=RefreshTokenInvalidationMode.ALL,
                ),
                detail=SubjectRefreshTokenSessionsDetail(subject_id="user-admin"),
            )

        assert "mode 必须与 detail.kind 一致" in str(fault.value)

    def test_token_session_detail_when_extra_field_should_fail(self) -> None:
        """
        验证指定令牌会话失效扩展禁止额外字段。
        """

        with pytest.raises(ValidationError) as fault:
            TokenSessionInvalidationDetail(
                token_session_id=TOKEN_SESSION_ID_VALUE,
                unexpected=True,
            )

        assert UNEXPECTED_FIELD_ERROR_FRAGMENT in str(fault.value)
