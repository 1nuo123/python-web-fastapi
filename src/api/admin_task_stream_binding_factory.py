"""管理员任务执行状态流生产绑定工厂。"""

from __future__ import annotations

from typing import Annotated, cast

from pydantic import BaseModel, Field, TypeAdapter

from src.api.fastapi_stream_route_composer import StreamOperationBinding
from src.application.admin.task_execution_stream_source import TaskExecutionStreamSource
from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.application.streaming.stream_execution_orchestrator import (
    StreamExecutionOrchestrator,
    StreamExecutionPolicy,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.core.stream_contract.stream_control_contract import (
    CancelControlDetail,
    PingControlDetail,
    ResumeControlDetail,
    StreamClientControlEnvelope,
    SubscribeControlDetail,
)
from src.core.stream_contract.stream_delivery_contract import (
    CommandStreamBindingDetail,
    SseDeliveryDetail,
    SseDeliveryMode,
    StreamCollectionLimit,
    StreamDeliveryKind,
    StreamOperationBindingEnvelope,
    StreamOperationBindingHeader,
)
from src.core.stream_contract.stream_event_contract import (
    StreamCompletedDetail,
    StreamEventEnvelope,
    StreamFaultDetail,
    StreamHeartbeatDetail,
    StreamProgressDetail,
    StreamStartedDetail,
    StreamTransport,
)
from src.core.task_contract.task_execution_stream_contract import (
    TaskExecutionSnapshotDetail,
    TaskExecutionWatchCommand,
)
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT,
)
from src.infrastructure.settings.application_settings import ApplicationSettings
from src.infrastructure.shared_resource_mount import SharedResourceMount
from src.infrastructure.streaming.deferred_stream_resources import (
    DeferredStreamSessionRegistry,
    DeferredStreamStateStore,
)
from src.infrastructure.streaming.http_batch_response_presenter import HttpBatchResponsePresenter
from src.infrastructure.streaming.production_websocket_admission_adapter import (
    ProductionWebSocketAdmissionAdapter,
)
from src.infrastructure.streaming.sse_response_presenter import SseResponsePresenter
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec
from src.infrastructure.streaming.stream_metrics_observer import (
    PrometheusStreamQueueSaturationObserver,
)
from src.infrastructure.streaming.streaming_runtime_factory import (
    StreamingOperationComponentSet,
)
from src.infrastructure.streaming.websocket_connection_guard import WebSocketConnectionGuard
from src.infrastructure.streaming.websocket_session_handler import WebSocketSessionHandler

ADMIN_TASK_STREAM_OPERATION_NAME = "admin_task_execution_watch"
ADMIN_TASK_STREAM_BATCH_SUFFIX = "/admin/tasks/executions/watch/batch"
ADMIN_TASK_STREAM_SSE_SUFFIX = "/admin/tasks/executions/watch/stream"
ADMIN_TASK_STREAM_WEBSOCKET_SUFFIX = "/admin/tasks/executions/watch/ws"
ADMIN_TASK_STREAM_TICKET_SUFFIX = "/admin/tasks/executions/watch/ticket"

AdminTaskStreamDetail = Annotated[
    StreamStartedDetail
    | StreamProgressDetail
    | StreamHeartbeatDetail
    | StreamCompletedDetail
    | StreamFaultDetail
    | TaskExecutionSnapshotDetail,
    Field(discriminator="kind"),
]
AdminTaskStreamControlDetail = Annotated[
    SubscribeControlDetail[TaskExecutionWatchCommand]
    | ResumeControlDetail
    | CancelControlDetail
    | PingControlDetail,
    Field(discriminator="kind"),
]


class AdminTaskStreamBindingFactory:
    """使用共享流运行时构建管理员任务生产绑定。"""

    def build(
        self,
        *,
        settings: ApplicationSettings,
        resource_mount: SharedResourceMount,
        response_factory: ResponseEnvelopeFactory,
    ) -> list[StreamOperationBinding[BaseModel, BaseModel, BaseModel]]:
        """构建复用同一任务事实源的 HTTP 与 SSE 生产绑定。"""

        detail = settings.runtime.stream.detail
        event_adapter = TypeAdapter(StreamEventEnvelope[AdminTaskStreamDetail])
        codec = StreamEventCodec(
            adapter=event_adapter,
            max_event_bytes=detail.max_event_bytes,
        )
        state_store = DeferredStreamStateStore(
            resources_provider=resource_mount.get_streaming_resources,
        )
        session_registry = DeferredStreamSessionRegistry(
            resources_provider=resource_mount.get_streaming_resources,
        )
        metrics_registry = resource_mount.get_metrics_registry()
        queue_saturation_observer = (
            PrometheusStreamQueueSaturationObserver(registry=metrics_registry)
            if metrics_registry is not None
            else None
        )
        orchestrator: StreamExecutionOrchestrator[
            TaskExecutionWatchCommand,
            AdminTaskStreamDetail,
        ] = StreamExecutionOrchestrator(
            event_adapter=event_adapter,
            policy=StreamExecutionPolicy(
                queue_capacity=detail.queue_capacity,
                send_timeout_seconds=detail.send_timeout_seconds,
                max_duration_seconds=detail.max_duration_seconds,
                max_event_bytes=detail.max_event_bytes,
            ),
            queue_saturation_observer=queue_saturation_observer,
        )
        control_adapter = TypeAdapter(StreamClientControlEnvelope[AdminTaskStreamControlDetail])
        source = TaskExecutionStreamSource(task_runtime_port=resource_mount)
        ticket_service = StreamAccessTicketService(
            state_store=state_store,
            ttl_seconds=detail.ticket_ttl_seconds,
        )
        admission_adapter = ProductionWebSocketAdmissionAdapter(
            resource_mount=resource_mount,
            operation_name=ADMIN_TASK_STREAM_OPERATION_NAME,
            authorization_requirement=ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT,
        )
        sse_presenter = SseResponsePresenter(
            codec=codec,
            heartbeat_seconds=detail.sse_heartbeat_seconds,
            retry_milliseconds=detail.sse_retry_milliseconds,
            send_timeout_seconds=detail.send_timeout_seconds,
        )
        websocket_guard = WebSocketConnectionGuard(
            allowed_origins=frozenset(detail.allowed_origins),
            require_browser_ticket=detail.require_browser_ticket,
            admission_port=admission_adapter,
            ticket_service=ticket_service,
            session_registry=session_registry,
        )
        websocket_handler = WebSocketSessionHandler(
            command_adapter=TypeAdapter(TaskExecutionWatchCommand),
            control_adapter=control_adapter,
            orchestrator=orchestrator,
            codec=codec,
            state_store=state_store,
            max_message_bytes=detail.websocket_max_message_bytes,
            send_timeout_seconds=detail.send_timeout_seconds,
            replay_ttl_seconds=detail.replay_ttl_seconds,
            replay_max_events=detail.replay_max_events,
            max_duration_seconds=detail.max_duration_seconds,
            metrics_registry=metrics_registry,
            runtime_provider=resource_mount.get_stream_runtime,
        )
        binding = StreamOperationBinding(
            contract=StreamOperationBindingEnvelope(
                header=StreamOperationBindingHeader(
                    operation_name=ADMIN_TASK_STREAM_OPERATION_NAME,
                    delivery_kind=StreamDeliveryKind.COMMAND,
                ),
                detail=CommandStreamBindingDetail(
                    batch_path=(
                        f"{settings.runtime.web.api_prefix}{ADMIN_TASK_STREAM_BATCH_SUFFIX}"
                    ),
                    sse_path=f"{settings.runtime.web.api_prefix}{ADMIN_TASK_STREAM_SSE_SUFFIX}",
                    sse_delivery=SseDeliveryDetail(
                        mode=SseDeliveryMode.BEARER_POST,
                        heartbeat_seconds=detail.sse_heartbeat_seconds,
                        retry_milliseconds=detail.sse_retry_milliseconds,
                        resume_enabled=True,
                        ticket_required=False,
                    ),
                    websocket_path=(
                        f"{settings.runtime.web.api_prefix}{ADMIN_TASK_STREAM_WEBSOCKET_SUFFIX}"
                    ),
                    ticket_path=(
                        f"{settings.runtime.web.api_prefix}{ADMIN_TASK_STREAM_TICKET_SUFFIX}"
                        if detail.require_browser_ticket
                        else None
                    ),
                    websocket_ticket_required=detail.require_browser_ticket,
                    transports=frozenset(
                        {
                            StreamTransport.HTTP,
                            StreamTransport.SSE,
                            StreamTransport.WEBSOCKET,
                        }
                    ),
                    resumable=True,
                ),
            ),
            command_adapter=TypeAdapter(TaskExecutionWatchCommand),
            event_adapter=event_adapter,
            control_adapter=control_adapter,
            source=source,
            orchestrator=orchestrator,
            codec=codec,
            batch_presenter=HttpBatchResponsePresenter(response_factory=response_factory),
            sse_presenter=sse_presenter,
            websocket_guard=websocket_guard,
            websocket_handler=websocket_handler,
            ticket_service=ticket_service,
            state_store=state_store,
            collection_limit=StreamCollectionLimit(
                max_events=detail.collection_max_events,
                max_bytes=detail.collection_max_bytes,
                timeout_seconds=detail.collection_timeout_seconds,
            ),
            replay_ttl_seconds=detail.replay_ttl_seconds,
            replay_max_events=detail.replay_max_events,
            max_duration_seconds=detail.max_duration_seconds,
            session_registry=session_registry,
            require_authenticated=True,
            authorization_requirement=ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT,
            authorization_guard=resource_mount.get_authorization_guard(),
            metrics_registry=metrics_registry,
            runtime_provider=resource_mount.get_stream_runtime,
            queue_saturation_observer=queue_saturation_observer,
        )
        resource_mount.register_streaming_operation_components(
            StreamingOperationComponentSet(
                orchestrator=cast(
                    StreamExecutionOrchestrator[BaseModel, BaseModel],
                    orchestrator,
                ),
                codec=cast(StreamEventCodec[BaseModel], codec),
                sse_presenter=cast(SseResponsePresenter[BaseModel], sse_presenter),
                websocket_guard=websocket_guard,
                websocket_handler=cast(
                    WebSocketSessionHandler[BaseModel, BaseModel, BaseModel],
                    websocket_handler,
                ),
            )
        )
        return cast(
            list[StreamOperationBinding[BaseModel, BaseModel, BaseModel]],
            [binding],
        )
