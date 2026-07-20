"""
FastAPI异常呈现器基础设施模块。
"""

from __future__ import annotations

import logging
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.types import ExceptionHandler

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.infrastructure.orjson_document_response import OrjsonDocumentResponse

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

MISSING_REQUEST_SCOPE_ID = "request-scope-missing"
REQUEST_VALIDATION_INTERNAL_DETAIL = "请求参数校验未通过。"
UNEXPECTED_EXCEPTION_INTERNAL_DETAIL = "未预期异常已记录到服务端日志。"


class FastApiExceptionPresenter:
    """
    FastAPI异常呈现器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(
        self,
        *,
        resource_mount: SharedResourceMount,
        logger: logging.Logger,
    ) -> None:
        """
        初始化FastAPI异常呈现器。

        :param resource_mount: 共享资源挂载点，用于构建和发送结构化日志事件。
        :type resource_mount: SharedResourceMount
        :param logger: 当前组件使用的日志记录器。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        self._resource_mount = resource_mount
        self._logger = logger
        self._response_factory = ResponseEnvelopeFactory()

    def bind(self, app: FastAPI) -> None:
        """
        处理绑定。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :returns: 无返回值。
        :rtype: None
        """

        app.add_exception_handler(
            HttpFaultException,
            cast(ExceptionHandler, self.handle_http_fault),
        )
        app.add_exception_handler(
            RequestValidationError,
            cast(ExceptionHandler, self.handle_request_validation),
        )
        app.add_exception_handler(Exception, self.handle_unexpected_exception)

    async def handle_http_fault(
        self, request: Request, exc: HttpFaultException
    ) -> OrjsonDocumentResponse:
        """
        处理处理HTTP故障。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param exc: 当前捕获到的异常对象。约束：需符合 ``HttpFaultException`` 注解。
        :type exc: HttpFaultException
        :returns: 返回当前操作结果。
        :rtype: OrjsonDocumentResponse
        """

        request_scope = self._read_request_scope(request)
        envelope = self._response_factory.build(
            code=str(exc.error_code),
            message=exc.message,
            request_scope=request_scope,
            data=exc.to_payload(),
        )
        log_event_builder = self._resource_mount.get_log_event_builder()
        self._resource_mount.emit_log_event(
            log_event_builder.build_exception_event(
                request_context=log_event_builder.build_request_context(request),
                exception=exc,
                status_code=exc.status_code,
                error_code=str(exc.error_code),
                include_traceback=False,
            )
        )
        self._logger.warning("请求失败：%s", exc.message)
        return OrjsonDocumentResponse(
            status_code=exc.status_code, content=envelope.model_dump(mode="json")
        )

    async def handle_request_validation(
        self,
        request: Request,
        exc: RequestValidationError,
    ) -> OrjsonDocumentResponse:
        """
        处理处理请求校验。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param exc: 当前捕获到的异常对象。约束：需符合 ``RequestValidationError`` 注解。
        :type exc: RequestValidationError
        :returns: 返回当前操作结果。
        :rtype: OrjsonDocumentResponse
        """

        request_scope = self._read_request_scope(request)
        fault = HttpFaultException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code=CoreErrorCode.REQUEST_INVALID,
            message="请求参数校验失败。",
            detail=REQUEST_VALIDATION_INTERNAL_DETAIL,
        )
        envelope = self._response_factory.build(
            code=str(CoreErrorCode.REQUEST_INVALID),
            message=fault.message,
            request_scope=request_scope,
            data=fault.to_payload(),
        )
        log_event_builder = self._resource_mount.get_log_event_builder()
        self._resource_mount.emit_log_event(
            log_event_builder.build_exception_event(
                request_context=log_event_builder.build_request_context(request),
                exception=fault,
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=str(CoreErrorCode.REQUEST_INVALID),
                include_traceback=False,
            )
        )
        return OrjsonDocumentResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content=envelope.model_dump(mode="json"),
        )

    async def handle_unexpected_exception(
        self, request: Request, exc: Exception
    ) -> OrjsonDocumentResponse:
        """
        处理处理未预期异常。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param exc: 当前捕获到的异常对象。约束：需符合 ``Exception`` 注解。
        :type exc: Exception
        :returns: 返回当前操作结果。
        :rtype: OrjsonDocumentResponse
        """

        request_scope = self._read_request_scope(request)
        fault = HttpFaultException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=CoreErrorCode.INTERNAL_UNEXPECTED,
            message="服务内部异常。",
            detail=UNEXPECTED_EXCEPTION_INTERNAL_DETAIL,
        )
        log_event_builder = self._resource_mount.get_log_event_builder()
        self._resource_mount.emit_log_event(
            log_event_builder.build_exception_event(
                request_context=log_event_builder.build_request_context(request),
                exception=exc,
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=str(CoreErrorCode.INTERNAL_UNEXPECTED),
                include_traceback=True,
            )
        )
        self._logger.error("发生未预期异常，已写入脱敏结构化日志。")
        envelope = self._response_factory.build(
            code=str(CoreErrorCode.INTERNAL_UNEXPECTED),
            message=fault.message,
            request_scope=request_scope,
            data=fault.to_payload(),
        )
        return OrjsonDocumentResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(mode="json"),
        )

    def _read_request_scope(self, request: Request) -> RequestScope:
        """
        读取请求作用域。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :returns: 返回当前操作结果。
        :rtype: RequestScope
        """

        request_scope = getattr(request.state, "request_scope", None)
        if isinstance(request_scope, RequestScope):
            return request_scope
        return RequestScope(
            request_id=MISSING_REQUEST_SCOPE_ID,
            trace_id=None,
            request_time_epoch=int(time.time()),
            request_path=request.url.path,
            request_method=request.method,
        )
