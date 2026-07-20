"""
敏感标识摘要服务模块。
"""

from __future__ import annotations

import hashlib
import hmac

SENSITIVE_DIGEST_ALGORITHM = "sha256"
SENSITIVE_DIGEST_MINIMUM_LENGTH = 1


class SensitiveDigestService:
    """
    敏感标识摘要服务。
    """

    def __init__(self, *, salt: str) -> None:
        """
        初始化敏感摘要服务。
        """

        if len(salt.strip()) < SENSITIVE_DIGEST_MINIMUM_LENGTH:
            raise ValueError("敏感摘要 salt 不能为空。")
        self._salt = salt.encode("utf-8")

    def digest(self, value: str) -> str:
        """
        生成稳定摘要。

        :param value: 敏感原文。
        :type value: str
        :returns: 十六进制摘要。
        :rtype: str
        """

        normalized = value.strip().encode("utf-8")
        return hmac.new(self._salt, normalized, hashlib.sha256).hexdigest()
