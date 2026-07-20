"""
管理员任务管理路由。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_admin_task.contract_admin_task import (
    ADMIN_TASK_QUERY_LIMIT_DEFAULT,
    ADMIN_TASK_QUERY_LIMIT_MAXIMUM,
    ADMIN_TASK_QUERY_LIMIT_MINIMUM,
    AdminTaskDispatchEnvelope,
    AdminTaskDispatchResultEnvelope,
    AdminTaskDispatchResultPayload,
    AdminTaskExecutionListEnvelope,
    AdminTaskExecutionListPayload,
    AdminTaskExecutionRecordEnvelope,
    AdminTaskExecutionRecordPayload,
    AdminTaskHeader,
    AdminTaskOperationName,
    AdminTaskPayloadKind,
    AdminTaskRegistrationListEnvelope,
    AdminTaskRegistrationListPayload,
    AdminTaskRuntimeEnvelope,
    AdminTaskRuntimePayload,
)
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.application.admin.dispatch_admin_task_usecase import (
    AdminTaskDispatchCommand,
)
from src.application.admin.list_admin_task_execution_records_usecase import (
    AdminTaskExecutionRecordListQuery,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.core.task_contract.task_execution_record_contract import TaskExecutionStatus
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_TASK_DISPATCH_AUTHORIZATION_REQUIREMENT,
    ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT,
)

ADMIN_TASK_ROUTE_TAG = "admin_task"
ADMIN_TASK_EXECUTIONS_PATH = "/admin/tasks/executions"
ADMIN_TASK_EXECUTION_RECORD_PATH = "/admin/tasks/executions/{task_id}"
ADMIN_TASK_RUNTIME_PATH = "/admin/tasks/runtime"
ADMIN_TASK_REGISTRATIONS_PATH = "/admin/tasks/registrations"
ADMIN_TASK_DISPATCH_PATH = "/admin/tasks/dispatch"
ADMIN_TASK_METHOD_GET = "GET"
ADMIN_TASK_METHOD_POST = "POST"
ADMIN_TASK_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
ADMIN_TASK_BEARER_SCHEME = HTTPBearer(auto_error=False)
ADMIN_TASK_LIST_SUCCESS_MESSAGE = "管理员任务执行记录查询成功。"
ADMIN_TASK_RECORD_SUCCESS_MESSAGE = "管理员任务执行记录读取成功。"
ADMIN_TASK_RUNTIME_SUCCESS_MESSAGE = "管理员任务运行时读取成功。"
ADMIN_TASK_REGISTRATION_SUCCESS_MESSAGE = "管理员任务注册信息查询成功。"
ADMIN_TASK_DISPATCH_SUCCESS_MESSAGE = "管理员任务派发成功。"
ADMIN_TASK_ID_DESCRIPTION = "任务执行标识。"
ADMIN_TASK_LIMIT_DESCRIPTION = "返回记录数量上限。"
ADMIN_TASK_STATUS_DESCRIPTION = "任务执行状态过滤。"
ADMIN_TASK_JOB_KIND_DESCRIPTION = "任务类型过滤。"


class AdminTaskRouteCatalog:
    """
    管理员任务管理路由目录。
    """

    def __init__(self) -> None:
        """
        初始化管理员任务管理路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[ADMIN_TASK_ROUTE_TAG])
        self.router.add_api_route(
            ADMIN_TASK_EXECUTIONS_PATH,
            self.list_task_executions,
            methods=[ADMIN_TASK_METHOD_GET],
            response_model=ResponseEnvelope[AdminTaskExecutionListEnvelope],
            dependencies=[Depends(self.require_task_query)],
        )
        self.router.add_api_route(
            ADMIN_TASK_EXECUTION_RECORD_PATH,
            self.get_task_execution,
            methods=[ADMIN_TASK_METHOD_GET],
            response_model=ResponseEnvelope[AdminTaskExecutionRecordEnvelope],
            dependencies=[Depends(self.require_task_query)],
        )
        self.router.add_api_route(
            ADMIN_TASK_RUNTIME_PATH,
            self.read_task_runtime,
            methods=[ADMIN_TASK_METHOD_GET],
            response_model=ResponseEnvelope[AdminTaskRuntimeEnvelope],
            dependencies=[Depends(self.require_task_query)],
        )
        self.router.add_api_route(
            ADMIN_TASK_REGISTRATIONS_PATH,
            self.list_task_registrations,
            methods=[ADMIN_TASK_METHOD_GET],
            response_model=ResponseEnvelope[AdminTaskRegistrationListEnvelope],
            dependencies=[Depends(self.require_task_query)],
        )
        self.router.add_api_route(
            ADMIN_TASK_DISPATCH_PATH,
            self.dispatch_task,
            methods=[ADMIN_TASK_METHOD_POST],
            response_model=ResponseEnvelope[AdminTaskDispatchResultEnvelope],
            dependencies=[Depends(self.require_task_dispatch)],
        )

    async def require_task_query(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_TASK_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员任务查询权限。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _credentials: OpenAPI Bearer 安全声明载荷。
        :type _credentials: HTTPAuthorizationCredentials | None
        :returns: 无返回值。
        :rtype: None
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT,
        )

    async def require_task_dispatch(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_TASK_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员任务派发权限。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _credentials: OpenAPI Bearer 安全声明载荷。
        :type _credentials: HTTPAuthorizationCredentials | None
        :returns: 无返回值。
        :rtype: None
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_TASK_DISPATCH_AUTHORIZATION_REQUIREMENT,
        )

    async def list_task_executions(
        self,
        request: Request,
        status: TaskExecutionStatus | None = Query(
            default=None,
            description=ADMIN_TASK_STATUS_DESCRIPTION,
        ),
        job_kind: str | None = Query(
            default=None,
            description=ADMIN_TASK_JOB_KIND_DESCRIPTION,
        ),
        limit: int = Query(
            default=ADMIN_TASK_QUERY_LIMIT_DEFAULT,
            ge=ADMIN_TASK_QUERY_LIMIT_MINIMUM,
            le=ADMIN_TASK_QUERY_LIMIT_MAXIMUM,
            description=ADMIN_TASK_LIMIT_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminTaskExecutionListEnvelope]:
        """
        查询管理员任务执行记录。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param status: 任务执行状态过滤。
        :type status: TaskExecutionStatus | None
        :param job_kind: 任务类型过滤。
        :type job_kind: str | None
        :param limit: 返回记录数量上限。
        :type limit: int
        :returns: 管理员任务执行记录列表响应。
        :rtype: ResponseEnvelope[AdminTaskExecutionListEnvelope]
        """

        records = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_TASK_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_task_execution_records_usecase(
                request
            ).execute,
            query=AdminTaskExecutionRecordListQuery(
                status=status,
                job_kind=job_kind,
                limit=limit,
            ),
        )
        detail = AdminTaskExecutionListPayload.from_records(records)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_TASK_LIST_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminTaskExecutionListEnvelope(
                header=AdminTaskHeader(
                    kind=AdminTaskPayloadKind.EXECUTION_LIST,
                    operation_name=AdminTaskOperationName.EXECUTION_LIST,
                ),
                detail=detail,
            ),
        )

    async def get_task_execution(
        self,
        request: Request,
        task_id: str = Path(description=ADMIN_TASK_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminTaskExecutionRecordEnvelope]:
        """
        读取管理员任务执行记录详情。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param task_id: 任务执行标识。
        :type task_id: str
        :returns: 管理员任务执行记录详情响应。
        :rtype: ResponseEnvelope[AdminTaskExecutionRecordEnvelope]
        """

        record = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_TASK_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_get_admin_task_execution_record_usecase(
                request
            ).execute,
            task_id=task_id,
        )
        detail = AdminTaskExecutionRecordPayload.from_record(record)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_TASK_RECORD_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminTaskExecutionRecordEnvelope(
                header=AdminTaskHeader(
                    kind=AdminTaskPayloadKind.EXECUTION_RECORD,
                    operation_name=AdminTaskOperationName.EXECUTION_RECORD,
                ),
                detail=detail,
            ),
        )

    async def read_task_runtime(
        self,
        request: Request,
    ) -> ResponseEnvelope[AdminTaskRuntimeEnvelope]:
        """
        读取管理员任务运行时信息。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务运行时响应。
        :rtype: ResponseEnvelope[AdminTaskRuntimeEnvelope]
        """

        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_TASK_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_admin_task_runtime_usecase(request).execute,
        )
        detail = AdminTaskRuntimePayload.from_result(result)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_TASK_RUNTIME_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminTaskRuntimeEnvelope(
                header=AdminTaskHeader(
                    kind=AdminTaskPayloadKind.RUNTIME,
                    operation_name=AdminTaskOperationName.RUNTIME_READ,
                ),
                detail=detail,
            ),
        )

    async def list_task_registrations(
        self,
        request: Request,
    ) -> ResponseEnvelope[AdminTaskRegistrationListEnvelope]:
        """
        查询管理员任务注册信息。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务注册列表响应。
        :rtype: ResponseEnvelope[AdminTaskRegistrationListEnvelope]
        """

        snapshots = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_TASK_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_task_registrations_usecase(
                request
            ).execute,
        )
        detail = AdminTaskRegistrationListPayload.from_snapshots(snapshots)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_TASK_REGISTRATION_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminTaskRegistrationListEnvelope(
                header=AdminTaskHeader(
                    kind=AdminTaskPayloadKind.REGISTRATION_LIST,
                    operation_name=AdminTaskOperationName.REGISTRATION_LIST,
                ),
                detail=detail,
            ),
        )

    async def dispatch_task(
        self,
        request: Request,
        command: AdminTaskDispatchEnvelope,
    ) -> ResponseEnvelope[AdminTaskDispatchResultEnvelope]:
        """
        执行管理员任务派发。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param command: 管理员任务派发请求信封。
        :type command: AdminTaskDispatchEnvelope
        :returns: 管理员任务派发结果响应。
        :rtype: ResponseEnvelope[AdminTaskDispatchResultEnvelope]
        """

        request_scope = self._accessor.read_request_scope(request)
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_TASK_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_dispatch_admin_task_usecase(request).execute,
            command=AdminTaskDispatchCommand(
                job_kind=command.detail.job_kind,
                payload_json=command.detail.payload_json,
                retry_limit=command.detail.retry_limit,
                deduplication_key=command.detail.deduplication_key,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
            ),
        )
        detail = AdminTaskDispatchResultPayload.from_result(result)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_TASK_DISPATCH_SUCCESS_MESSAGE,
            request_scope=request_scope,
            data=AdminTaskDispatchResultEnvelope(
                header=AdminTaskHeader(
                    kind=AdminTaskPayloadKind.DISPATCH_RESULT,
                    operation_name=AdminTaskOperationName.DISPATCH_RESULT,
                ),
                detail=detail,
            ),
        )


class AdminTaskBundleProvider(WebBundleProvider):
    """
    管理员任务管理模块提供者。
    """

    module_name = ApplicationModuleName.ADMIN_TASK.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供管理员任务管理模块信封。

        :returns: Web 模块提供者信封。
        :rtype: WebBundleProviderEnvelope
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=AdminTaskRouteCatalog().router,
            ),
        )
