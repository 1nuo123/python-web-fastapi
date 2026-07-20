"""
模拟时钟基础设施模块。
"""

from __future__ import annotations


class FakeClock:
    """
    模拟时钟类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, initial_value: float = 0.0) -> None:
        """
        初始化模拟时钟。

        :param initial_value: 当前步骤使用的initial值参数。默认值：`0.0`。约束：需符合 ``float`` 注解。
        :type initial_value: float
        :returns: 无返回值。
        :rtype: None
        """

        self._value = initial_value

    def now(self) -> float:
        """
        处理当前。

        :returns: 返回当前操作结果。
        :rtype: float
        """

        return self._value

    def advance(self, seconds: float) -> None:
        """
        处理推进。

        :param seconds: 当前步骤使用的秒数参数。约束：需符合 ``float`` 注解。
        :type seconds: float
        :returns: 无返回值。
        :rtype: None
        """

        self._value += seconds
