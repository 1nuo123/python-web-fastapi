"""
任务执行 Outbox 发布器单元测试模块。
"""

from __future__ import annotations

import logging
from typing import NoReturn

from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessageBusBackend,
    MessagePublishResult,
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.orm_model.task_execution_outbox_orm_model import (
    TaskExecutionOutboxOrmModel,
    TaskExecutionOutboxStatus,
)
from src.infrastructure.task.local_message_bus import LocalMessageBus
from src.infrastructure.task.task_execution_outbox_publisher import (
    TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH,
    TaskExecutionOutboxPublisher,
)
from src.infrastructure.task.task_execution_store import (
    TaskExecutionStore,
)
from src.infrastructure.testing.task_execution_test_support import (
    TEST_CREATED_AT_EPOCH,
    TEST_DEDUPLICATION_KEY,
    TEST_JOB_KIND,
    TEST_PAYLOAD_JSON,
    TEST_PAYLOAD_KIND,
    TEST_QUEUE_NAME,
    TEST_TASK_ID,
    TaskExecutionRecordBuilder,
    TaskExecutionStoreTestFactory,
    TaskExecutionTestContext,
)

OUTBOX_MESSAGE_ID = "outbox-message-1"
OUTBOX_FAILURE_MESSAGE_ID = "outbox-message-failure"
OUTBOX_MARK_FAILURE_MESSAGE_ID = "outbox-message-mark-failure"
OUTBOX_PUBLISH_FAILURE_TEXT = "发布失败。"
OUTBOX_MARK_PUBLISHED_FAILURE_TEXT = "标记发布失败。"
OUTBOX_FAILURE_REPEAT_COUNT = 200
OUTBOX_TEST_LIMIT = 10
OUTBOX_STALE_BEFORE_EPOCH = TEST_CREATED_AT_EPOCH + 1
OUTBOX_FUTURE_BEFORE_EPOCH = TEST_CREATED_AT_EPOCH - 1
OUTBOX_BACKGROUND_INTERVAL_SECONDS = 0.01
OUTBOX_BACKGROUND_STALE_SECONDS = 0
OUTBOX_INITIAL_ATTEMPT_COUNT = 0
OUTBOX_SUCCESS_ATTEMPT_COUNT = 1
OUTBOX_TEST_LOGGER = logging.getLogger("test_task_execution_outbox_publisher")


class FakeMessageBus(MessageBus):
    """
    发布成功的消息总线测试替身。
    """

    def __init__(self) -> None:
        """
        初始化消息总线测试替身。
        """

        self.published_messages: list[TaskMessageEnvelope] = []

    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        记录消息并返回发布成功。
        """

        self.published_messages.append(message)
        return MessagePublishResult.build_succeeded(
            message_id=message.header.message_id,
            routed=True,
        )

    @property
    def backend(self) -> MessageBusBackend:
        """
        读取消息总线后端。
        """

        return MessageBusBackend.LOCAL

    def close(self) -> None:
        """
        释放测试资源。
        """

        self.published_messages.clear()


class FailingMessageBus(FakeMessageBus):
    """
    发布失败的消息总线测试替身。
    """

    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        抛出发布失败异常。
        """

        _ = message
        raise RuntimeError(OUTBOX_PUBLISH_FAILURE_TEXT * OUTBOX_FAILURE_REPEAT_COUNT)


class MarkPublishedFailOnceStore:
    """
    首次标记发布失败的任务执行存储替身。
    """

    def __init__(self, *, wrapped_store: TaskExecutionStore) -> None:
        """
        初始化任务执行存储替身。
        """

        self._wrapped_store = wrapped_store
        self._mark_published_failed = False
        self.mark_outbox_failed_count = 0

    def list_reserved_outbox(
        self,
        *,
        limit: int,
        created_before_epoch: int | None = None,
    ) -> list[TaskExecutionOutboxOrmModel]:
        """
        列出待发布 Outbox 记录。
        """

        return self._wrapped_store.list_reserved_outbox(
            limit=limit,
            created_before_epoch=created_before_epoch,
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
    ):
        """
        首次调用时模拟标记发布失败。
        """

        if not self._mark_published_failed:
            self._mark_published_failed = True
            raise RuntimeError(OUTBOX_MARK_PUBLISHED_FAILURE_TEXT)
        return self._wrapped_store.mark_published(
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            attempt_count=attempt_count,
            backend=backend,
            queue_name=queue_name,
            message_id=message_id,
        )

    def mark_outbox_failed(
        self,
        *,
        message_id: str,
        failure_reason: str,
    ) -> NoReturn:
        """
        记录错误的失败标记调用并中断测试。
        """

        _ = message_id
        _ = failure_reason
        self.mark_outbox_failed_count += 1
        raise AssertionError("发布成功后不得把 Outbox 标记为失败。")


class TestTaskExecutionOutboxPublisherUnit:
    """
    任务执行 Outbox 发布器单元测试集合。
    """

    def test_publish_reserved_should_publish_message_and_mark_record_published(
        self,
    ) -> None:
        """
        验证 Outbox 发布器发布待投递消息并标记执行记录。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = FakeMessageBus()
        try:
            message = self._build_message(OUTBOX_MESSAGE_ID)
            test_context.store.reserve_with_outbox(
                record=TaskExecutionRecordBuilder().build(
                    task_id=TEST_TASK_ID,
                    deduplication_key=TEST_DEDUPLICATION_KEY,
                ),
                message=message,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
            )
            publisher = TaskExecutionOutboxPublisher(
                task_execution_store=test_context.store,
                local_message_bus=message_bus,
                logger=OUTBOX_TEST_LOGGER,
            )

            result = publisher.publish_reserved(limit=OUTBOX_TEST_LIMIT)
            record = test_context.store.get_by_task_id(TEST_TASK_ID)
            outbox_record = self._read_outbox_record(
                test_context=test_context,
                message_id=OUTBOX_MESSAGE_ID,
            )

            assert result.scanned_count == 1
            assert result.published_count == 1
            assert result.failed_count == 0
            assert [message.header.message_id for message in message_bus.published_messages] == [
                OUTBOX_MESSAGE_ID
            ]
            assert record is not None
            assert record.detail.status == TaskExecutionStatus.PUBLISHED
            assert outbox_record.status == TaskExecutionOutboxStatus.PUBLISHED.value
        finally:
            message_bus.close()
            test_context.close()

    def test_mark_published_when_consumer_finished_should_preserve_success(
        self,
    ) -> None:
        """验证快速消费完成后发布回写不得把成功状态回退为已发布。"""

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            message = self._build_message(OUTBOX_MESSAGE_ID)
            test_context.store.reserve_with_outbox(
                record=TaskExecutionRecordBuilder().build(
                    task_id=TEST_TASK_ID,
                    deduplication_key=TEST_DEDUPLICATION_KEY,
                ),
                message=message,
                backend=TaskBackend.FUNBOOST,
                queue_name=TEST_QUEUE_NAME,
            )
            test_context.store.mark_running(
                job_kind=TEST_JOB_KIND,
                deduplication_key=TEST_DEDUPLICATION_KEY,
                attempt_count=OUTBOX_INITIAL_ATTEMPT_COUNT,
                backend=TaskBackend.FUNBOOST,
                queue_name=TEST_QUEUE_NAME,
                stage=TaskExecutionStage.CONSUME_EXECUTION,
            )
            test_context.store.mark_success(
                job_kind=TEST_JOB_KIND,
                deduplication_key=TEST_DEDUPLICATION_KEY,
                attempt_count=OUTBOX_SUCCESS_ATTEMPT_COUNT,
                backend=TaskBackend.FUNBOOST,
                queue_name=TEST_QUEUE_NAME,
                stage=TaskExecutionStage.CONSUME_EXECUTION,
            )

            published_record = test_context.store.mark_published(
                job_kind=TEST_JOB_KIND,
                deduplication_key=TEST_DEDUPLICATION_KEY,
                attempt_count=OUTBOX_INITIAL_ATTEMPT_COUNT,
                backend=TaskBackend.FUNBOOST,
                queue_name=TEST_QUEUE_NAME,
                message_id=OUTBOX_MESSAGE_ID,
            )
            outbox_record = self._read_outbox_record(
                test_context=test_context,
                message_id=OUTBOX_MESSAGE_ID,
            )

            assert published_record.status == TaskExecutionStatus.SUCCESS.value
            assert published_record.stage == TaskExecutionStage.CONSUME_EXECUTION.value
            assert outbox_record.status == TaskExecutionOutboxStatus.PUBLISHED.value
        finally:
            test_context.close()

    def test_publish_reserved_when_created_after_stale_window_should_skip(
        self,
    ) -> None:
        """
        验证 Outbox 重扫只发布已进入陈旧窗口的记录。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = FakeMessageBus()
        try:
            message = self._build_message(OUTBOX_MESSAGE_ID)
            test_context.store.reserve_with_outbox(
                record=TaskExecutionRecordBuilder().build(
                    task_id=TEST_TASK_ID,
                    deduplication_key=TEST_DEDUPLICATION_KEY,
                ),
                message=message,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
            )
            publisher = TaskExecutionOutboxPublisher(
                task_execution_store=test_context.store,
                local_message_bus=message_bus,
                logger=OUTBOX_TEST_LOGGER,
            )

            skipped_result = publisher.publish_reserved(
                limit=OUTBOX_TEST_LIMIT,
                created_before_epoch=OUTBOX_FUTURE_BEFORE_EPOCH,
            )
            published_result = publisher.publish_reserved(
                limit=OUTBOX_TEST_LIMIT,
                created_before_epoch=OUTBOX_STALE_BEFORE_EPOCH,
            )

            assert skipped_result.scanned_count == 0
            assert published_result.scanned_count == 1
            assert [message.header.message_id for message in message_bus.published_messages] == [
                OUTBOX_MESSAGE_ID
            ]
        finally:
            message_bus.close()
            test_context.close()

    def test_publish_reserved_when_publish_failed_should_mark_outbox_failed(
        self,
    ) -> None:
        """
        验证发布失败时 Outbox 记录会写入截断后的失败原因。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = FailingMessageBus()
        try:
            message = self._build_message(OUTBOX_FAILURE_MESSAGE_ID)
            test_context.store.reserve_with_outbox(
                record=TaskExecutionRecordBuilder().build(
                    task_id=TEST_TASK_ID,
                    deduplication_key=TEST_DEDUPLICATION_KEY,
                ),
                message=message,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
            )
            publisher = TaskExecutionOutboxPublisher(
                task_execution_store=test_context.store,
                local_message_bus=message_bus,
                logger=OUTBOX_TEST_LOGGER,
            )

            result = publisher.publish_reserved(limit=OUTBOX_TEST_LIMIT)
            outbox_record = self._read_outbox_record(
                test_context=test_context,
                message_id=OUTBOX_FAILURE_MESSAGE_ID,
            )

            assert result.scanned_count == 1
            assert result.published_count == 0
            assert result.failed_count == 1
            assert outbox_record.status == TaskExecutionOutboxStatus.FAILED.value
            assert outbox_record.failure_reason is not None
            assert (
                len(outbox_record.failure_reason) == TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH
            )
        finally:
            message_bus.close()
            test_context.close()

    def test_publish_reserved_after_commit_before_publish_crash_should_rescan(
        self,
    ) -> None:
        """
        验证数据库提交后发布前崩溃留下的 RESERVED 记录可被重扫发布。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = FakeMessageBus()
        try:
            message = self._build_message(OUTBOX_MESSAGE_ID)
            test_context.store.reserve_with_outbox(
                record=TaskExecutionRecordBuilder().build(
                    task_id=TEST_TASK_ID,
                    deduplication_key=TEST_DEDUPLICATION_KEY,
                ),
                message=message,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
            )
            reserved_record = self._read_outbox_record(
                test_context=test_context,
                message_id=OUTBOX_MESSAGE_ID,
            )
            publisher = TaskExecutionOutboxPublisher(
                task_execution_store=test_context.store,
                local_message_bus=message_bus,
                logger=OUTBOX_TEST_LOGGER,
            )

            result = publisher.publish_reserved(limit=OUTBOX_TEST_LIMIT)
            published_record = self._read_outbox_record(
                test_context=test_context,
                message_id=OUTBOX_MESSAGE_ID,
            )

            assert reserved_record.status == TaskExecutionOutboxStatus.RESERVED.value
            assert result.published_count == 1
            assert published_record.status == TaskExecutionOutboxStatus.PUBLISHED.value
        finally:
            message_bus.close()
            test_context.close()

    def test_publish_reserved_when_mark_published_failed_should_retry_idempotently(
        self,
    ) -> None:
        """
        验证发布成功但标记失败时保留重扫能力并避免本地重复消息。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = LocalMessageBus()
        store = MarkPublishedFailOnceStore(wrapped_store=test_context.store)
        try:
            message = self._build_message(OUTBOX_MARK_FAILURE_MESSAGE_ID)
            test_context.store.reserve_with_outbox(
                record=TaskExecutionRecordBuilder().build(
                    task_id=TEST_TASK_ID,
                    deduplication_key=TEST_DEDUPLICATION_KEY,
                ),
                message=message,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
            )
            publisher = TaskExecutionOutboxPublisher(
                task_execution_store=store,
                local_message_bus=message_bus,
                logger=OUTBOX_TEST_LOGGER,
            )

            first_result = publisher.publish_reserved(limit=OUTBOX_TEST_LIMIT)
            second_result = publisher.publish_reserved(limit=OUTBOX_TEST_LIMIT)
            outbox_record = self._read_outbox_record(
                test_context=test_context,
                message_id=OUTBOX_MARK_FAILURE_MESSAGE_ID,
            )
            record = test_context.store.get_by_task_id(TEST_TASK_ID)

            assert first_result.scanned_count == 1
            assert first_result.published_count == 0
            assert first_result.failed_count == 1
            assert second_result.published_count == 1
            assert store.mark_outbox_failed_count == 0
            assert [
                published_message.header.message_id
                for published_message in message_bus.list_messages()
            ] == [OUTBOX_MARK_FAILURE_MESSAGE_ID]
            assert outbox_record.status == TaskExecutionOutboxStatus.PUBLISHED.value
            assert record is not None
            assert record.detail.status == TaskExecutionStatus.PUBLISHED
        finally:
            message_bus.close()
            test_context.close()

    def test_background_worker_should_start_and_shutdown_cleanly(self) -> None:
        """
        验证后台 Outbox worker 启停会回收线程资源。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = FakeMessageBus()
        try:
            publisher = TaskExecutionOutboxPublisher(
                task_execution_store=test_context.store,
                local_message_bus=message_bus,
                logger=OUTBOX_TEST_LOGGER,
                background_enabled=True,
                background_interval_seconds=OUTBOX_BACKGROUND_INTERVAL_SECONDS,
                background_stale_seconds=OUTBOX_BACKGROUND_STALE_SECONDS,
                background_limit=OUTBOX_TEST_LIMIT,
            )

            assert publisher._runner._worker is not None  # noqa: SLF001

            publisher.shutdown()

            assert publisher._runner._worker is None  # noqa: SLF001
        finally:
            message_bus.close()
            test_context.close()

    def _build_message(self, message_id: str) -> TaskMessageEnvelope:
        """
        构建任务消息。
        """

        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=message_id,
                created_at_epoch=TEST_CREATED_AT_EPOCH,
            ),
            payload=TaskMessagePayload(
                job_kind=TEST_JOB_KIND,
                deduplication_key=TEST_DEDUPLICATION_KEY,
                retry_limit=OUTBOX_TEST_LIMIT,
                payload_kind=TEST_PAYLOAD_KIND,
                payload_json=TEST_PAYLOAD_JSON,
            ),
        )

    def _read_outbox_record(
        self,
        *,
        test_context: TaskExecutionTestContext,
        message_id: str,
    ) -> TaskExecutionOutboxOrmModel:
        """
        读取 Outbox 记录。
        """

        session = test_context.session_factory.create_session()
        try:
            record = (
                session.query(TaskExecutionOutboxOrmModel)
                .filter(TaskExecutionOutboxOrmModel.message_id == message_id)
                .one()
            )
            session.expunge(record)
            return record
        finally:
            session.close()
