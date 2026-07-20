"""
OAuth2方案提供器基础设施模块。
"""

from __future__ import annotations

from fastapi import Request

AUTHORIZATION_HEADER_NAME = "Authorization"
BEARER_AUTHORIZATION_SCHEME = "bearer"


class OAuth2SchemeProvider:
    """
    O鉴权2方案提供器，负责向调用方暴露统一访问入口。
    """

    def extract_bearer_token(self, request: Request) -> str | None:
        """
        提取Bearer令牌。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :returns: 返回当前操作结果。
        :rtype: str | None
        """

        authorization_value = request.headers.get(AUTHORIZATION_HEADER_NAME)
        if authorization_value is None:
            return None
        parts = authorization_value.strip().split(" ", 1)
        if len(parts) != 2:
            return None
        scheme, token_value = parts
        if scheme.lower() != BEARER_AUTHORIZATION_SCHEME:
            return None
        token = token_value.strip()
        return token or None
