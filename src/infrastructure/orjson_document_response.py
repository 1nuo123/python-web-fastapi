"""
orjson文档响应基础设施模块。
"""

from __future__ import annotations

import orjson
from fastapi.responses import JSONResponse


class OrjsonDocumentResponse(JSONResponse):
    """
    orjson文档响应模型，用于承载接口响应数据。

    :ivar media_type: ``media_type`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'application/json'`。取值语义：用于承载当前对象中的业务状态。
    :vartype media_type: str
    """

    media_type = "application/json"

    def render(self, content: object) -> bytes:
        """
        处理渲染。

        :param content: 待渲染的响应内容。约束：需符合 ``object`` 注解。
        :type content: object
        :returns: 返回当前操作结果。
        :rtype: bytes
        """

        return orjson.dumps(content)
