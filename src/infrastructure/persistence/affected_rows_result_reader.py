"""SQLAlchemy 受影响行数结果读取器。"""

from __future__ import annotations

from typing import Protocol, cast


class AffectedRowsResult(Protocol):
    """声明数据修改结果的受影响行数字段。"""

    rowcount: int | None


class AffectedRowsResultReader:
    """统一读取 SQLAlchemy 数据修改语句的受影响行数。"""

    @staticmethod
    def read(execution_result: object) -> int:
        """读取受影响行数。

        :param execution_result: SQLAlchemy 数据修改执行结果。
        :type execution_result: object
        :returns: 非负受影响行数。
        :rtype: int
        """

        result = cast(AffectedRowsResult, execution_result)
        return int(result.rowcount or 0)
