"""
Web集合契约核心契约模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fastapi import APIRouter


class ApplicationModuleName(StrEnum):
    """
    应用模块名称枚举，用于约束可选取值。

    :cvar HEALTH_PROBE: ``HEALTH_PROBE`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'health_probe'`。取值语义：用于承载当前对象中的业务状态。
    :vartype HEALTH_PROBE: str
    :cvar SYSTEM_OVERVIEW: ``SYSTEM_OVERVIEW`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system_overview'`。取值语义：用于承载当前对象中的业务状态。
    :vartype SYSTEM_OVERVIEW: str
    :cvar AUTH_ACCESS: ``AUTH_ACCESS`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_access'`。取值语义：用于承载当前对象中的业务状态。
    :vartype AUTH_ACCESS: str
    """

    HEALTH_PROBE = "health_probe"
    SYSTEM_OVERVIEW = "system_overview"
    AUTH_ACCESS = "auth_access"
    SECURITY_PROTECTION = "security_protection"
    ADMIN_TASK = "admin_task"
    ADMIN_SETTINGS = "admin_settings"
    ADMIN_LOG = "admin_log"
    ADMIN_IDENTITY = "admin_identity"
    ADMIN_AUDIT = "admin_audit"


@dataclass(slots=True)
class WebBundle:
    """
    Web集合数据对象，用于承载当前流程的结构化字段。

    :ivar module_name: ``module_name`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：使用 Web manifest 的模块名作为业务键。
    :vartype module_name: str
    :ivar router: ``router`` 字段。约束：需符合 ``APIRouter`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype router: APIRouter
    """

    module_name: str
    router: APIRouter
