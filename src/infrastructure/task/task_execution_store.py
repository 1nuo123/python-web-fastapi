"""
任务执行记录存储模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time

from sqlalchemy.exc import IntegrityError

from src.core.task_contract.message_bus_contract import TaskMessageEnvelope
from src.core.task_contract.task_execution_record_contract import (
    TASK_EXECUTION_RECORD_KIND,
    TASK_EXECUTION_RECORD_SCHEMA_VERSION,
    TaskExecutionCreatedDetail,
    TaskExecutionDedupeDetailKind,
    TaskExecutionDedupeDetailUnion,
    TaskExecutionDedupeHeader,
    TaskExecutionDedupeResult,
    TaskExecutionExistingDetail,
    TaskExecutionFailedDetail,
    TaskExecutionPendingDetail,
    TaskExecutionPublishedDetail,
    TaskExecutionRecordDetailKind,
    TaskExecutionRecordDetailUnion,
    TaskExecutionRecordEnvelope,
    TaskExecutionRecordHeader,
    TaskExecutionReservedDetail,
    TaskExecutionRetryingDetail,
    TaskExecutionRunningDetail,
    TaskExecutionStage,
    TaskExecutionStatus,
    TaskExecutionSuccessDetail,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
    TaskExecutionMetric,
    TaskExecutionMetricOutcome,
)
from src.infrastructure.persistence.orm_model.task_execution_outbox_orm_model import (
    TaskExecutionOutboxOrmModel,
    TaskExecutionOutboxStatus,
)
from src.infrastructure.persistence.orm_model.task_execution_record_orm_model import (
    TaskExecutionRecordOrmModel,
)
from src.infrastructure.persistence.repository_impl.task_execution_outbox_repository_impl import (
    TaskExecutionOutboxRepositoryImpl,
    TaskExecutionOutboxUpdatePayload,
)
from src.infrastructure.persistence.repository_impl.task_execution_record_repository_impl import (
    TASK_EXECUTION_DEDUPE_CONFLICT_MESSAGE,
    TaskExecutionDedupeConflictLookupError,
    TaskExecutionRecordRepositoryImpl,
    TaskExecutionRecordUpdatePayload,
    TaskExecutionRecordUpsertResult,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)

DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT = 0
TASK_EXECUTION_RECORD_NOT_FOUND_MESSAGE = "任务执行记录不存在。"
TASK_EXECUTION_OUTBOX_NOT_FOUND_MESSAGE = "任务执行 Outbox 记录不存在。"
TASK_EXECUTION_BEFORE_PUBLISH_STATUSES = frozenset(
    {
        TaskExecutionStatus.PENDING,
        TaskExecutionStatus.RESERVED,
    }
)


class TaskExecutionRecordNotFoundError(RuntimeError):
    """
    任务执行记录不存在异常。
    """


class TaskExecutionOutboxNotFoundError(RuntimeError):
    """
    任务执行 Outbox 记录不存在异常。
    """


@dataclass(slots=True)
class TaskExecutionStoreResult:
    """
    任务执行记录存储结果。
    """

    record: TaskExecutionRecordOrmModel
    created: bool
    dedupe_result: TaskExecutionDedupeResult
    outbox_record: TaskExecutionOutboxOrmModel | None = None


class TaskExecutionStore:
    """
    任务执行记录存储服务。
    """

    def __init__(
        self,
        *,
        session_manager: SharedDbSessionManager,
        metrics_registry: PrometheusMetricsRegistry | None = None,
    ) -> None:
        """
        初始化任务执行记录存储。

        :param session_manager: 共享数据库会话管理器。
        :type session_manager: SharedDbSessionManager
        :param metrics_registry: Prometheus 指标注册器；``None`` 时不挂接任务执行指标。
        :type metrics_registry: PrometheusMetricsRegistry | None
        :returns: 无返回值。
        :rtype: None
        """

        self._session_manager = session_manager
        self._metrics_registry = metrics_registry

    def _record_task_execution_metric(
        self,
        *,
        job_kind: str,
        outcome: TaskExecutionMetricOutcome,
    ) -> None:
        """
        记录任务执行指标。

        :param job_kind: 任务注册名。
        :type job_kind: str
        :param outcome: 任务执行结果。
        :type outcome: TaskExecutionMetricOutcome
        :returns: 无返回值。
        :rtype: None
        """

        if self._metrics_registry is None:
            return
        self._metrics_registry.record_task_execution(
            TaskExecutionMetric(task_name=job_kind, outcome=outcome)
        )

    def reserve(
        self,
        *,
        record: TaskExecutionRecordOrmModel,
    ) -> TaskExecutionStoreResult:
        """
        预占任务执行记录。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionRecordRepositoryImpl(unit_of_work.get_session())
            try:
                result: TaskExecutionRecordUpsertResult = repository.insert(record)
                unit_of_work.commit()
            except IntegrityError as exc:
                unit_of_work.rollback()
                if not repository.is_dedupe_unique_constraint_violation(exc):
                    raise
                result = TaskExecutionRecordUpsertResult(
                    record=self._read_conflict_record(record),
                    created=False,
                )
            if not result.created:
                self._record_task_execution_metric(
                    job_kind=record.job_kind,
                    outcome=TaskExecutionMetricOutcome.REJECTED,
                )
            return TaskExecutionStoreResult(
                record=result.record,
                created=result.created,
                dedupe_result=self.build_dedupe_result(
                    record=result.record,
                    created=result.created,
                ),
            )
        finally:
            unit_of_work.dispose()

    def reserve_with_outbox(
        self,
        *,
        record: TaskExecutionRecordOrmModel,
        message: TaskMessageEnvelope,
        backend: TaskBackend,
        queue_name: str,
    ) -> TaskExecutionStoreResult:
        """
        在同一事务中预占执行记录并写入待发布 Outbox。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = TaskExecutionRecordRepositoryImpl(session)
            outbox_repository = TaskExecutionOutboxRepositoryImpl(session)
            try:
                result = repository.insert(record)
                outbox_record = self._build_outbox_record(
                    message=message,
                    backend=backend,
                    queue_name=queue_name,
                )
                outbox_repository.insert(outbox_record)
                unit_of_work.commit()
            except IntegrityError as exc:
                unit_of_work.rollback()
                if not repository.is_dedupe_unique_constraint_violation(exc):
                    raise
                result = TaskExecutionRecordUpsertResult(
                    record=self._read_conflict_record(record),
                    created=False,
                )
                outbox_record = None
            if not result.created:
                self._record_task_execution_metric(
                    job_kind=record.job_kind,
                    outcome=TaskExecutionMetricOutcome.REJECTED,
                )
            return TaskExecutionStoreResult(
                record=result.record,
                created=result.created,
                dedupe_result=self.build_dedupe_result(
                    record=result.record,
                    created=result.created,
                ),
                outbox_record=outbox_record,
            )
        finally:
            unit_of_work.dispose()

    def _read_conflict_record(
        self,
        record: TaskExecutionRecordOrmModel,
    ) -> TaskExecutionRecordOrmModel:
        """
        使用新的工作单元读取去重冲突后的既有执行记录。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionRecordRepositoryImpl(unit_of_work.get_session())
            conflict_record = repository.get_by_job_and_deduplication_key(
                job_kind=record.job_kind,
                deduplication_key=record.deduplication_key,
            )
            if conflict_record is None:
                raise TaskExecutionDedupeConflictLookupError(TASK_EXECUTION_DEDUPE_CONFLICT_MESSAGE)
            return conflict_record
        finally:
            unit_of_work.dispose()

    def get_by_task_id(self, task_id: str) -> TaskExecutionRecordEnvelope | None:
        """
        按任务标识读取执行记录信封。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionRecordRepositoryImpl(unit_of_work.get_session())
            record = repository.get_by_task_id(task_id)
            if record is None:
                return None
            return self.build_envelope(record)
        finally:
            unit_of_work.dispose()

    def list_records(
        self,
        *,
        limit: int,
        status: TaskExecutionStatus | None = None,
        job_kind: str | None = None,
    ) -> list[TaskExecutionRecordEnvelope]:
        """
        查询任务执行记录信封。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionRecordRepositoryImpl(unit_of_work.get_session())
            return [
                self.build_envelope(record)
                for record in repository.list_records(
                    limit=limit,
                    status=status,
                    job_kind=job_kind,
                )
            ]
        finally:
            unit_of_work.dispose()

    def mark_running(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        backend: TaskBackend,
        queue_name: str,
        stage: TaskExecutionStage,
    ) -> TaskExecutionRecordOrmModel:
        """
        标记执行中。
        """

        return self._update_record(
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            patch=TaskExecutionRecordUpdatePayload(
                status=TaskExecutionStatus.RUNNING,
                backend=backend,
                attempt_count=attempt_count,
                queue_name=queue_name,
                stage=stage,
                started_at_epoch=int(time()),
            ),
        )

    def mark_published(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        backend: TaskBackend,
        queue_name: str,
        message_id: str | None = None,
        outbox_attempt_count: int | None = None,
    ) -> TaskExecutionRecordOrmModel:
        """
        标记消息已发布。
        """

        published_at_epoch = int(time())
        return self._update_record(
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            patch=TaskExecutionRecordUpdatePayload(
                status=TaskExecutionStatus.PUBLISHED,
                backend=backend,
                attempt_count=attempt_count,
                queue_name=queue_name,
                stage=TaskExecutionStage.DISPATCH,
                published_at_epoch=published_at_epoch,
            ),
            outbox_message_id=message_id,
            outbox_patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.PUBLISHED,
                published_at_epoch=published_at_epoch,
                attempt_count=outbox_attempt_count,
            )
            if message_id is not None
            else None,
            allowed_current_statuses=TASK_EXECUTION_BEFORE_PUBLISH_STATUSES,
        )

    def mark_retrying(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        next_retry_at_epoch: int,
        last_error_type: str,
        last_error_message: str,
        backend: TaskBackend,
        queue_name: str,
        stage: TaskExecutionStage,
    ) -> TaskExecutionRecordOrmModel:
        """
        标记重试中。
        """

        return self._update_record(
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            patch=TaskExecutionRecordUpdatePayload(
                status=TaskExecutionStatus.RETRYING,
                backend=backend,
                attempt_count=attempt_count,
                queue_name=queue_name,
                next_retry_at_epoch=next_retry_at_epoch,
                last_error_type=last_error_type,
                last_error_message=last_error_message,
                stage=stage,
            ),
        )

    def mark_success(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        backend: TaskBackend,
        queue_name: str,
        stage: TaskExecutionStage,
    ) -> TaskExecutionRecordOrmModel:
        """
        标记成功。
        """

        record = self._update_record(
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            patch=TaskExecutionRecordUpdatePayload(
                status=TaskExecutionStatus.SUCCESS,
                backend=backend,
                attempt_count=attempt_count,
                queue_name=queue_name,
                finished_at_epoch=int(time()),
                stage=stage,
            ),
        )
        self._record_task_execution_metric(
            job_kind=job_kind,
            outcome=TaskExecutionMetricOutcome.SUCCESS,
        )
        return record

    def mark_failed(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        failed_at_epoch: int,
        last_error_type: str,
        last_error_message: str,
        backend: TaskBackend,
        queue_name: str,
        stage: TaskExecutionStage,
        message_id: str | None = None,
    ) -> TaskExecutionRecordOrmModel:
        """
        标记失败。
        """

        record = self._update_record(
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            patch=TaskExecutionRecordUpdatePayload(
                status=TaskExecutionStatus.FAILED,
                backend=backend,
                attempt_count=attempt_count,
                queue_name=queue_name,
                failed_at_epoch=failed_at_epoch,
                last_error_type=last_error_type,
                last_error_message=last_error_message,
                stage=stage,
            ),
            outbox_message_id=message_id,
            outbox_patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.FAILED,
                failed_at_epoch=failed_at_epoch,
                failure_reason=last_error_message,
            )
            if message_id is not None
            else None,
        )
        self._record_task_execution_metric(
            job_kind=job_kind,
            outcome=TaskExecutionMetricOutcome.FAILED,
        )
        return record

    def try_mark_failed(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        failed_at_epoch: int,
        last_error_type: str,
        last_error_message: str,
        backend: TaskBackend,
        queue_name: str,
        stage: TaskExecutionStage,
    ) -> TaskExecutionRecordOrmModel | None:
        """
        尝试标记失败，记录缺失时返回空值。
        """

        try:
            return self.mark_failed(
                job_kind=job_kind,
                deduplication_key=deduplication_key,
                attempt_count=attempt_count,
                failed_at_epoch=failed_at_epoch,
                last_error_type=last_error_type,
                last_error_message=last_error_message,
                backend=backend,
                queue_name=queue_name,
                stage=stage,
            )
        except TaskExecutionRecordNotFoundError:
            return None

    def mark_outbox_published(self, *, message_id: str) -> TaskExecutionOutboxOrmModel:
        """
        标记 Outbox 消息已发布。
        """

        return self._update_outbox_record(
            message_id=message_id,
            patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.PUBLISHED,
                published_at_epoch=int(time()),
            ),
        )

    def mark_outbox_retrying(
        self,
        *,
        message_id: str,
        attempt_count: int,
        next_retry_at_epoch: int,
        last_error_type: str,
        last_error_message: str,
    ) -> TaskExecutionOutboxOrmModel:
        """记录可恢复的基础设施投递失败。"""

        return self._update_outbox_record(
            message_id=message_id,
            patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.RETRYING,
                attempt_count=attempt_count,
                next_retry_at_epoch=next_retry_at_epoch,
                last_error_type=last_error_type,
                last_error_message=last_error_message,
                failure_reason=last_error_message,
            ),
        )

    def mark_outbox_unknown(
        self,
        *,
        message_id: str,
        attempt_count: int,
        error_type: str,
        error_message: str,
    ) -> TaskExecutionOutboxOrmModel:
        """记录发布成功但本地确认未知的 Outbox 结果。"""

        now_epoch = int(time())
        return self._update_outbox_record(
            message_id=message_id,
            patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.UNKNOWN,
                attempt_count=attempt_count,
                unknown_at_epoch=now_epoch,
                last_error_type=error_type,
                last_error_message=error_message,
                failure_reason=error_message,
            ),
        )

    def mark_outbox_failed_permanent(
        self,
        *,
        message_id: str,
        attempt_count: int,
        error_type: str,
        error_message: str,
    ) -> TaskExecutionOutboxOrmModel:
        """记录达到投递尝试上限的永久失败。"""

        return self._update_outbox_record(
            message_id=message_id,
            patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.FAILED_PERMANENT,
                attempt_count=attempt_count,
                failed_at_epoch=int(time()),
                last_error_type=error_type,
                last_error_message=error_message,
                failure_reason=error_message,
            ),
        )

    def retry_unknown_outbox(self, *, message_id: str) -> TaskExecutionOutboxOrmModel:
        """受控地将未知结果重新纳入唯一 Outbox runner。"""

        return self._update_outbox_record(
            message_id=message_id,
            patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.RETRYING,
                next_retry_at_epoch=int(time()),
            ),
        )

    def list_unknown_outbox(
        self,
        *,
        limit: int,
    ) -> list[TaskExecutionOutboxOrmModel]:
        """列出等待诊断或人工恢复的未知结果。"""

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionOutboxRepositoryImpl(unit_of_work.get_session())
            return repository.list_by_status(
                status=TaskExecutionOutboxStatus.UNKNOWN,
                limit=limit,
            )
        finally:
            unit_of_work.dispose()

    def mark_outbox_failed(
        self,
        *,
        message_id: str,
        failure_reason: str,
    ) -> TaskExecutionOutboxOrmModel:
        """
        标记 Outbox 消息发布失败。
        """

        return self._update_outbox_record(
            message_id=message_id,
            patch=TaskExecutionOutboxUpdatePayload(
                status=TaskExecutionOutboxStatus.FAILED,
                failed_at_epoch=int(time()),
                failure_reason=failure_reason,
            ),
        )

    def list_reserved_outbox(
        self,
        *,
        limit: int,
        created_before_epoch: int | None = None,
        claim_owner: str | None = None,
    ) -> list[TaskExecutionOutboxOrmModel]:
        """
        列出待发布 Outbox 记录。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionOutboxRepositoryImpl(unit_of_work.get_session())
            records = repository.list_reserved(
                limit=limit,
                created_before_epoch=created_before_epoch,
                claim_owner=claim_owner,
            )
            if claim_owner is not None and records:
                unit_of_work.commit()
            return records
        finally:
            unit_of_work.dispose()

    def build_envelope(
        self,
        record: TaskExecutionRecordOrmModel,
    ) -> TaskExecutionRecordEnvelope:
        """
        构建执行记录信封。
        """

        status = TaskExecutionStatus(record.status)
        stage = TaskExecutionStage(record.stage or TaskExecutionStage.DISPATCH.value)
        detail: TaskExecutionRecordDetailUnion
        if status == TaskExecutionStatus.PENDING:
            detail = TaskExecutionPendingDetail(attempt_count=record.attempt_count)
        elif status == TaskExecutionStatus.RESERVED:
            detail = TaskExecutionReservedDetail(attempt_count=record.attempt_count)
        elif status == TaskExecutionStatus.PUBLISHED:
            detail = TaskExecutionPublishedDetail(
                attempt_count=record.attempt_count,
                published_at_epoch=record.published_at_epoch or record.created_at_epoch,
            )
        elif status == TaskExecutionStatus.RUNNING:
            detail = TaskExecutionRunningDetail(
                attempt_count=record.attempt_count,
                stage=stage,
                started_at_epoch=record.started_at_epoch or record.created_at_epoch,
            )
        elif status == TaskExecutionStatus.RETRYING:
            detail = TaskExecutionRetryingDetail(
                attempt_count=record.attempt_count,
                stage=stage,
                next_retry_at_epoch=record.next_retry_at_epoch or record.created_at_epoch,
                last_error_type=record.last_error_type or "",
                last_error_message=record.last_error_message or "",
            )
        elif status == TaskExecutionStatus.SUCCESS:
            detail = TaskExecutionSuccessDetail(
                attempt_count=record.attempt_count,
                stage=stage,
                finished_at_epoch=record.finished_at_epoch or record.created_at_epoch,
            )
        else:
            detail = TaskExecutionFailedDetail(
                attempt_count=record.attempt_count,
                failed_at_epoch=record.failed_at_epoch or record.created_at_epoch,
                last_error_type=record.last_error_type or "",
                last_error_message=record.last_error_message or "",
                stage=stage,
            )
        header = TaskExecutionRecordHeader(
            detail_kind=TaskExecutionRecordDetailKind(detail.kind),
            record_id=record.record_id,
            task_id=record.task_id,
            job_kind=record.job_kind,
            deduplication_key=record.deduplication_key,
            backend=TaskBackend(record.backend),
            queue_name=record.queue_name or "",
            request_id=record.request_id,
            trace_id=record.trace_id,
            created_at_epoch=record.created_at_epoch,
        )
        return TaskExecutionRecordEnvelope(header=header, detail=detail)

    def build_dedupe_result(
        self,
        *,
        record: TaskExecutionRecordOrmModel,
        created: bool,
    ) -> TaskExecutionDedupeResult:
        """
        构建任务执行去重结果信封。
        """

        status = TaskExecutionStatus(record.status)
        detail: TaskExecutionDedupeDetailUnion
        if created:
            detail = TaskExecutionCreatedDetail(status=status)
            detail_kind = TaskExecutionDedupeDetailKind.CREATED
        else:
            detail = TaskExecutionExistingDetail(status=status)
            detail_kind = TaskExecutionDedupeDetailKind.EXISTING
        return TaskExecutionDedupeResult(
            header=TaskExecutionDedupeHeader(
                kind=TASK_EXECUTION_RECORD_KIND,
                schema_version=TASK_EXECUTION_RECORD_SCHEMA_VERSION,
                detail_kind=detail_kind,
                record_id=record.record_id,
                job_kind=record.job_kind,
                deduplication_key=record.deduplication_key,
            ),
            detail=detail,
        )

    def _update_record(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        patch: TaskExecutionRecordUpdatePayload,
        outbox_message_id: str | None = None,
        outbox_patch: TaskExecutionOutboxUpdatePayload | None = None,
        allowed_current_statuses: frozenset[TaskExecutionStatus] | None = None,
    ) -> TaskExecutionRecordOrmModel:
        """
        更新指定执行记录。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = TaskExecutionRecordRepositoryImpl(session)
            record = repository.get_by_job_and_deduplication_key(
                job_kind=job_kind,
                deduplication_key=deduplication_key,
                lock_for_update=True,
            )
            if record is None:
                raise TaskExecutionRecordNotFoundError(TASK_EXECUTION_RECORD_NOT_FOUND_MESSAGE)
            if allowed_current_statuses is None:
                repository.update_fields(record, patch)
            else:
                status_updated = repository.update_fields_when_status_in(
                    record,
                    patch,
                    allowed_current_statuses,
                )
                if not status_updated and patch.published_at_epoch is not None:
                    repository.update_fields(
                        record,
                        TaskExecutionRecordUpdatePayload(
                            published_at_epoch=patch.published_at_epoch,
                        ),
                    )
            if outbox_message_id is not None and outbox_patch is not None:
                outbox_repository = TaskExecutionOutboxRepositoryImpl(session)
                outbox_record = outbox_repository.get_by_message_id(outbox_message_id)
                if outbox_record is None:
                    raise TaskExecutionOutboxNotFoundError(TASK_EXECUTION_OUTBOX_NOT_FOUND_MESSAGE)
                outbox_repository.update_fields(outbox_record, outbox_patch)
            unit_of_work.commit()
            return record
        finally:
            unit_of_work.dispose()

    def _update_outbox_record(
        self,
        *,
        message_id: str,
        patch: TaskExecutionOutboxUpdatePayload,
    ) -> TaskExecutionOutboxOrmModel:
        """
        更新指定 Outbox 记录。
        """

        unit_of_work = self._session_manager.create_unit_of_work()
        try:
            repository = TaskExecutionOutboxRepositoryImpl(unit_of_work.get_session())
            record = repository.get_by_message_id(message_id)
            if record is None:
                raise TaskExecutionOutboxNotFoundError(TASK_EXECUTION_OUTBOX_NOT_FOUND_MESSAGE)
            repository.update_fields(record, patch)
            unit_of_work.commit()
            return record
        finally:
            unit_of_work.dispose()

    def _build_outbox_record(
        self,
        *,
        message: TaskMessageEnvelope,
        backend: TaskBackend,
        queue_name: str,
    ) -> TaskExecutionOutboxOrmModel:
        """
        构建任务执行 Outbox 记录。
        """

        return TaskExecutionOutboxOrmModel(
            message_id=message.header.message_id,
            job_kind=message.payload.job_kind,
            deduplication_key=message.payload.deduplication_key,
            backend=backend.value,
            queue_name=queue_name,
            payload_kind=message.payload.payload_kind,
            message_json=message.model_dump_json(),
            status=TaskExecutionOutboxStatus.RESERVED.value,
            created_at_epoch=message.header.created_at_epoch,
        )
