"""
HTTP故障契约核心契约模块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

HTTP_FAULT_SCHEMA_VERSION = "1.0"
HTTP_FAULT_KIND = "http_fault"


class HttpFaultPayload(BaseModel):
    """
    HTTP故障Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`HTTP_FAULT_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`HTTP_FAULT_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar status_code: ``status_code`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype status_code: int
    :ivar error_code: ``error_code`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype error_code: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=HTTP_FAULT_KIND)
    schema_version: str = Field(default=HTTP_FAULT_SCHEMA_VERSION)
    status_code: int
    error_code: str


class HttpFaultException(Exception):
    """
    HTTP故障异常类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        """
        初始化HTTP故障异常。

        :param status_code: HTTP 状态码。约束：需符合 ``int`` 注解。
        :type status_code: int
        :param error_code: 稳定错误码。约束：需符合 ``str`` 注解。
        :type error_code: str
        :param message: 消息对象或消息文本。约束：需符合 ``str`` 注解。
        :type message: str
        :param detail: 附加诊断信息。默认值：`None`。约束：需符合 ``str | None`` 注解。
        :type detail: str | None
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail

    def to_payload(self) -> HttpFaultPayload:
        """
        处理到载荷。

        :returns: 返回当前操作结果。
        :rtype: HttpFaultPayload
        """

        return HttpFaultPayload(
            status_code=self.status_code,
            error_code=self.error_code,
        )
