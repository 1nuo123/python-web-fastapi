"""
安全运行时契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.http_contract.security_runtime_contract import (
    DEVELOPMENT_SECURITY_KIND,
    PRODUCTION_SECURITY_KIND,
    DevelopmentSecurityRuntimeDetail,
    ProductionSecurityRuntimeDetail,
    SecurityRuntimeEnvelope,
    SecurityRuntimeHeader,
    SecurityRuntimeMode,
)


class TestSecurityRuntimeContract:
    """
    安全运行时契约测试集合。
    """

    def test_envelope_when_production_detail_should_keep_header_and_detail_consistent(
        self,
    ) -> None:
        """
        验证生产安全信封应保持公共头与扩展字段一致。
        """

        envelope = SecurityRuntimeEnvelope(
            header=SecurityRuntimeHeader(
                mode=SecurityRuntimeMode.PRODUCTION,
                enabled=True,
                policy_name="production_public_baseline",
            ),
            detail=ProductionSecurityRuntimeDetail(),
        )

        assert envelope.header.mode == SecurityRuntimeMode.PRODUCTION
        assert envelope.detail.kind == PRODUCTION_SECURITY_KIND

    def test_envelope_when_development_detail_should_accept_debug_policy(self) -> None:
        """
        验证开发安全信封应允许开发态公开面策略。
        """

        envelope = SecurityRuntimeEnvelope(
            header=SecurityRuntimeHeader(
                mode=SecurityRuntimeMode.DEVELOPMENT,
                enabled=True,
                policy_name="development_default",
            ),
            detail=DevelopmentSecurityRuntimeDetail(
                expose_openapi=True,
                expose_system_info=False,
                require_external_jwt_secret=False,
                require_distributed_auth_throttle=False,
                enable_hsts=False,
                enable_csp=False,
            ),
        )

        assert envelope.detail.kind == DEVELOPMENT_SECURITY_KIND

    def test_envelope_when_mode_and_detail_mismatch_should_fail(self) -> None:
        """
        验证公共头模式与扩展类型不一致时应失败。
        """

        with pytest.raises(ValidationError) as fault:
            SecurityRuntimeEnvelope(
                header=SecurityRuntimeHeader(
                    mode=SecurityRuntimeMode.PRODUCTION,
                    enabled=True,
                    policy_name="production_public_baseline",
                ),
                detail=DevelopmentSecurityRuntimeDetail(
                    expose_openapi=True,
                    expose_system_info=False,
                    require_external_jwt_secret=False,
                    require_distributed_auth_throttle=False,
                    enable_hsts=False,
                    enable_csp=False,
                ),
            )

        assert "mode 必须与 detail.kind 一致" in str(fault.value)

    def test_detail_when_unknown_field_should_forbid_extra(self) -> None:
        """
        验证安全扩展字段禁止额外字段。
        """

        with pytest.raises(ValidationError) as fault:
            ProductionSecurityRuntimeDetail.model_validate(
                {
                    "kind": PRODUCTION_SECURITY_KIND,
                    "schema_version": "1.0",
                    "expose_openapi": False,
                    "expose_system_info": False,
                    "require_external_jwt_secret": True,
                    "require_distributed_auth_throttle": True,
                    "enable_hsts": True,
                    "enable_csp": True,
                    "metadata": {},
                }
            )

        assert "metadata" in str(fault.value)
