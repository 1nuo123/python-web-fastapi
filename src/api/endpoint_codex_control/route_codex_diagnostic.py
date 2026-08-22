"""Codex 浏览器客户端脱敏诊断接收路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticReceipt,
)
from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceReceipt,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.codex_authorization_policy import CODEX_READ_AUTHORIZATION_REQUIREMENT

CODEX_DIAGNOSTIC_BEARER_SCHEME = HTTPBearer(auto_error=False)


class CodexDiagnosticRouteCatalog:
    """注册认证后才可访问的浏览器客户端诊断接收接口。"""

    def __init__(self) -> None:
        """初始化独立子路由，避免把诊断传输耦合到会话正文接口。"""

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter()
        self.router.add_api_route(
            "/codex/diagnostics",
            self.record_diagnostic,
            methods=["POST"],
            response_model=ResponseEnvelope[CodexClientDiagnosticReceipt],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/diagnostics/performance",
            self.record_performance,
            methods=["POST"],
            response_model=ResponseEnvelope[CodexClientPerformanceReceipt],
            dependencies=[Depends(self.require_codex_read)],
        )

    async def require_codex_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(
            CODEX_DIAGNOSTIC_BEARER_SCHEME
        ),
    ) -> None:
        """校验用户认证与 ``codex:read`` scope。"""

        self._accessor.read_authorized_principal(request, CODEX_READ_AUTHORIZATION_REQUIREMENT)

    async def record_diagnostic(
        self,
        request: Request,
        body: CodexClientDiagnosticEnvelope,
    ) -> ResponseEnvelope[CodexClientDiagnosticReceipt]:
        """
        接收无正文的客户端诊断并返回抑制状态。

        限流抑制仍返回成功响应，浏览器不会重试或缓存该请求；这保证诊断链路不能成为
        会话发送、认证或恢复流程的可用性依赖。

        :param request: 当前已完成认证与授权的 HTTP 请求。
        :type request: Request
        :param body: 严格类型化的客户端诊断信封。
        :type body: CodexClientDiagnosticEnvelope
        :returns: 是否由当前进程写入安全日志的诊断回执。
        :rtype: ResponseEnvelope[CodexClientDiagnosticReceipt]
        """

        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        if not runtime.settings.client_diagnostic_error_collection_enabled:
            return self._accessor.read_response_factory(request).build(
                code=str(SuccessCode.OK),
                message="Codex客户端诊断采集当前未启用。",
                request_scope=self._accessor.read_request_scope(request),
                data=CodexClientDiagnosticReceipt(recorded=False),
            )
        receipt = runtime.record_client_diagnostic.execute(
            owner_subject_id=principal.subject_id,
            envelope=body,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex客户端诊断已接收。",
            request_scope=self._accessor.read_request_scope(request),
            data=receipt,
        )

    async def record_performance(
        self,
        request: Request,
        body: CodexClientPerformanceEnvelope,
    ) -> ResponseEnvelope[CodexClientPerformanceReceipt]:
        """
        接收默认关闭的无正文性能样本。

        此接口不触发浏览器上传或重试。仅当服务端开关已明确启用时，手动或后续受控
        传输才会进入记录器；关闭时仍返回成功回执以保持可观测性旁路不影响会话操作。

        :param request: 当前已完成认证与授权的 HTTP 请求。
        :type request: Request
        :param body: 只包含受限枚举、单位和数值的性能诊断信封。
        :type body: CodexClientPerformanceEnvelope
        :returns: 是否由当前实例写入结构化性能样本的回执。
        :rtype: ResponseEnvelope[CodexClientPerformanceReceipt]
        """

        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        if not runtime.settings.client_diagnostic_performance_collection_enabled:
            return self._accessor.read_response_factory(request).build(
                code=str(SuccessCode.OK),
                message="Codex客户端性能采集当前未启用。",
                request_scope=self._accessor.read_request_scope(request),
                data=CodexClientPerformanceReceipt(recorded=False),
            )
        receipt = runtime.record_client_performance.execute(envelope=body)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex客户端性能样本已接收。",
            request_scope=self._accessor.read_request_scope(request),
            data=receipt,
        )
