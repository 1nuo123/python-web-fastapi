"""
载荷守卫中间件基础设施模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, TypedDict, cast

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.infrastructure.orjson_document_response import OrjsonDocumentResponse
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

CONTENT_LENGTH_HEADER_NAME = "content-length"
HTTP_REQUEST_MESSAGE_TYPE = "http.request"
HTTP_RESPONSE_START_MESSAGE_TYPE = "http.response.start"
HTTP_SCOPE_TYPE = "http"
MIDDLEWARE_TRACE_NAME = "payload_guard"
REQUEST_PAYLOAD_TOO_LARGE_MESSAGE = "请求体过大。"
SCOPE_MIDDLEWARE_TRACE_KEY = "middleware_trace"
SCOPE_REQUEST_STATE_KEY = "state"
SCOPE_REQUEST_SCOPE_KEY = "request_scope"
SCOPE_PATH_KEY = "path"
SCOPE_METHOD_KEY = "method"


class PayloadGuardScopeState(TypedDict, total=False):
    """
    载荷守卫作用域状态TypedDict 映射，用于描述结构化字典输入。

    :ivar middleware_trace: ``middleware_trace`` 字段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype middleware_trace: list[str]
    :ivar request_scope: ``request_scope`` 字段。约束：需符合 ``RequestScope`` 注解。默认值：无，必须显式提供。取值语义：用于声明授权作用域或请求作用域。
    :vartype request_scope: RequestScope
    """

    middleware_trace: list[str]
    request_scope: RequestScope


class RequestPayloadTooLargeSignal(Exception):
    """
    请求载荷过于过大信号异常，用于在链路内部中断或切换流程。
    """

    pass


@dataclass(slots=True)
class ResponseStartTracker:
    """
    响应开始跟踪器数据对象，用于承载当前流程的结构化字段。

    :ivar downstream_send: ``downstream_send`` 字段。约束：需符合 ``Send`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype downstream_send: Send
    :ivar started: ``started`` 字段。约束：需符合 ``bool`` 注解。默认值：`False`。取值语义：用于承载当前对象中的业务状态。
    :vartype started: bool
    """

    downstream_send: Send
    started: bool = False

    async def send(self, message: Message) -> None:
        """
        处理发送。

        :param message: 消息对象或消息文本。约束：需符合 ``Message`` 注解。
        :type message: Message
        :returns: 无返回值。
        :rtype: None
        """

        if message["type"] == HTTP_RESPONSE_START_MESSAGE_TYPE:
            self.started = True
        await self.downstream_send(message)


@dataclass(slots=True)
class PayloadLimitedReceive:
    """
    载荷受限接收数据对象，用于承载当前流程的结构化字段。

    :ivar upstream_receive: ``upstream_receive`` 字段。约束：需符合 ``Receive`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype upstream_receive: Receive
    :ivar request_limit: ``request_limit`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype request_limit: int
    :ivar received_bytes: ``received_bytes`` 字段。约束：需符合 ``int`` 注解。默认值：`0`。取值语义：用于承载当前对象中的业务状态。
    :vartype received_bytes: int
    """

    upstream_receive: Receive
    request_limit: int
    received_bytes: int = 0

    async def __call__(self) -> Message:
        """
        执行当前可调用对象。

        :returns: 返回当前操作结果。
        :rtype: Message
        :raises RequestPayloadTooLargeSignal: 当累计读取的请求体字节数超过限制时抛出。
        """

        message = await self.upstream_receive()
        if message["type"] != HTTP_REQUEST_MESSAGE_TYPE:
            return message
        self.received_bytes += len(message.get("body", b""))
        if self.received_bytes > self.request_limit:
            raise RequestPayloadTooLargeSignal
        return message


class PayloadGuardMiddleware:
    """
    载荷守卫中间件，负责拦截并增强请求链路。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_mount: SharedResourceMount,
    ) -> None:
        """
        初始化载荷守卫中间件。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``ASGIApp`` 注解。
        :type app: ASGIApp
        :param resource_mount: 共享资源挂载点。
        :type resource_mount: SharedResourceMount
        :returns: 无返回值。
        :rtype: None
        """

        self._app = app
        self._resource_mount = resource_mount
        self._response_factory = ResponseEnvelopeFactory()
        self._security_event_builder = SecurityEventBuilder()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        执行当前中间件的调用链处理。

        :param scope: ASGI 作用域对象。约束：需符合 ``Scope`` 注解。
        :type scope: Scope
        :param receive: ASGI 接收函数。约束：需符合 ``Receive`` 注解。
        :type receive: Receive
        :param send: ASGI 发送函数。约束：需符合 ``Send`` 注解。
        :type send: Send
        :returns: 无返回值。
        :rtype: None
        :raises Exception: 当底层依赖发生未预期故障时继续向上抛出。
        """

        if scope["type"] != HTTP_SCOPE_TYPE:
            await self._app(scope, receive, send)
            return
        scope_state = self._read_scope_state(scope)
        self._append_middleware_trace(scope_state)
        request_limit = (
            self._resource_mount.read_runtime_bundle().settings.runtime.web.max_request_body_bytes
        )
        content_length = self._read_content_length(scope)
        if content_length is not None and content_length > request_limit:
            # 头部已经明确超限时直接拒绝，避免继续读取大包体占用链路资源。
            await self._send_payload_too_large_response(
                scope=scope,
                scope_state=scope_state,
                limit_bytes=request_limit,
                receive=receive,
                send=send,
            )
            return
        limited_receive = PayloadLimitedReceive(
            upstream_receive=receive,
            request_limit=request_limit,
        )
        response_start_tracker = ResponseStartTracker(downstream_send=send)
        try:
            # 即使 content-length 被伪造，也通过流式累计字节数做最终兜底校验。
            await self._app(scope, limited_receive, response_start_tracker.send)
        except RequestPayloadTooLargeSignal:
            if response_start_tracker.started:
                # 下游已经开始写响应头时无法再切换统一错误包，交由上层按异常处理。
                raise
            await self._send_payload_too_large_response(
                scope=scope,
                scope_state=scope_state,
                limit_bytes=request_limit,
                receive=receive,
                send=send,
            )

    def _read_scope_state(self, scope: Scope) -> PayloadGuardScopeState:
        """
        读取作用域状态。

        :param scope: ASGI 作用域对象。约束：需符合 ``Scope`` 注解。
        :type scope: Scope
        :returns: 返回当前操作结果。
        :rtype: PayloadGuardScopeState
        """

        raw_state = scope.setdefault(SCOPE_REQUEST_STATE_KEY, {})
        return cast(PayloadGuardScopeState, raw_state)

    def _append_middleware_trace(self, scope_state: PayloadGuardScopeState) -> None:
        """
        处理追加中间件跟踪。

        :param scope_state: 挂载在 ASGI 作用域中的中间态字典。约束：需符合 ``PayloadGuardScopeState`` 注解。
        :type scope_state: PayloadGuardScopeState
        :returns: 无返回值。
        :rtype: None
        """

        middleware_trace = scope_state.get("middleware_trace")
        if middleware_trace is None:
            return
        middleware_trace.append(MIDDLEWARE_TRACE_NAME)

    def _read_content_length(self, scope: Scope) -> int | None:
        """
        读取内容长度。

        :param scope: ASGI 作用域对象。约束：需符合 ``Scope`` 注解。
        :type scope: Scope
        :returns: 返回当前操作结果。
        :rtype: int | None
        """

        for header_name, header_value in scope["headers"]:
            if header_name.decode("latin-1").lower() != CONTENT_LENGTH_HEADER_NAME:
                continue
            try:
                return int(header_value.decode("latin-1"))
            except ValueError:
                return None
        return None

    async def _send_payload_too_large_response(
        self,
        *,
        scope: Scope,
        scope_state: PayloadGuardScopeState,
        limit_bytes: int,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        处理发送载荷过于过大响应。

        :param scope: ASGI 作用域对象。约束：需符合 ``Scope`` 注解。
        :type scope: Scope
        :param scope_state: 挂载在 ASGI 作用域中的中间态字典。约束：需符合 ``PayloadGuardScopeState`` 注解。
        :type scope_state: PayloadGuardScopeState
        :param receive: ASGI 接收函数。约束：需符合 ``Receive`` 注解。
        :type receive: Receive
        :param send: ASGI 发送函数。约束：需符合 ``Send`` 注解。
        :type send: Send
        :returns: 无返回值。
        :rtype: None
        """

        # 413 响应也复用统一信封结构，确保异常路径与正常路径具有一致的接口契约。
        request_scope = scope_state["request_scope"]
        self._emit_payload_security_event(
            scope=scope,
            request_scope=request_scope,
            limit_bytes=limit_bytes,
        )
        fault = HttpFaultException(
            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            error_code=CoreErrorCode.REQUEST_PAYLOAD_TOO_LARGE,
            message=REQUEST_PAYLOAD_TOO_LARGE_MESSAGE,
        )
        envelope = self._response_factory.build(
            code=str(fault.error_code),
            message=fault.message,
            request_scope=request_scope,
            data=fault.to_payload(),
        )
        response = OrjsonDocumentResponse(
            status_code=fault.status_code,
            content=envelope.model_dump(mode="json"),
        )
        await response(scope, receive, send)

    def _emit_payload_security_event(
        self,
        *,
        scope: Scope,
        request_scope: RequestScope,
        limit_bytes: int,
    ) -> None:
        """
        写入请求体过大安全事件。
        """
        event = self._security_event_builder.build_payload_event(
            request_scope=request_scope,
            path=str(scope[SCOPE_PATH_KEY]),
            method=str(scope[SCOPE_METHOD_KEY]),
            limit_bytes=limit_bytes,
        )
        self._resource_mount.emit_security_event(event)
