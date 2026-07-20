"""
请求上下文管理器实现基础设施模块。
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request

from src.core.http_contract.request_scope_contract import RequestScope

REQUEST_SCOPE_CONTEXT: ContextVar[RequestScope | None] = ContextVar(
    "request_scope_context",
    default=None,
)


class RequestContextManagerImpl:
    """
    请求上下文管理器实现类型，用于封装当前模块中的相关行为或状态。
    """

    def build_scope(
        self,
        *,
        request: Request,
        request_id: str,
        trace_id: str | None,
        request_time_epoch: int,
    ) -> RequestScope:
        """
        构建作用域。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param request_id: 请求唯一标识。约束：需符合 ``str`` 注解。
        :type request_id: str
        :param trace_id: 链路追踪标识。约束：需符合 ``str | None`` 注解。
        :type trace_id: str | None
        :param request_time_epoch: 请求进入链路时记录的 Unix 时间戳秒值。约束：需符合 ``int`` 注解。
        :type request_time_epoch: int
        :returns: 返回当前步骤新建的对象。
        :rtype: RequestScope
        """

        return RequestScope(
            request_id=request_id,
            trace_id=trace_id,
            request_time_epoch=request_time_epoch,
            request_path=request.url.path,
            request_method=request.method,
        )

    def set_current_scope(self, scope: RequestScope) -> None:
        """
        设置当前作用域。

        :param scope: ASGI 作用域对象。约束：需符合 ``RequestScope`` 注解。
        :type scope: RequestScope
        :returns: 无返回值。
        :rtype: None
        """

        REQUEST_SCOPE_CONTEXT.set(scope)

    def get_current_scope(self) -> RequestScope | None:
        """
        获取当前作用域。

        :returns: 返回读取到的对象或状态快照。
        :rtype: RequestScope | None
        """

        return REQUEST_SCOPE_CONTEXT.get()

    def bind_authenticated_subject(self, subject_id: str) -> None:
        """
        绑定已认证主体。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 无返回值。
        :rtype: None
        """

        scope = self.get_current_scope()
        if scope is None:
            return
        REQUEST_SCOPE_CONTEXT.set(scope.model_copy(update={"authenticated_subject_id": subject_id}))

    def clear_current_scope(self) -> None:
        """
        清理当前作用域。

        :returns: 无返回值。
        :rtype: None
        """

        REQUEST_SCOPE_CONTEXT.set(None)
