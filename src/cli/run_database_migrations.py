"""
数据库迁移命令行入口。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.infrastructure.logging.app_logger_factory import AppLoggerFactory
from src.infrastructure.persistence.alembic_runner import AlembicRunner
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader

DATABASE_MIGRATION_EXIT_SUCCESS = 0
DATABASE_MIGRATION_EXIT_FAILURE = 1
MIGRATION_JOB_SCHEMA_VERSION: Final = "1.0"
MIGRATION_JOB_RESULT_KIND: Final = "migration_job_result"
MIGRATION_JOB_OPERATION_NAME: Final = "database_migration"
MIGRATION_JOB_FAILURE_MESSAGE = "数据库迁移失败。"


class MigrationJobStatus(StrEnum):
    """
    数据库迁移任务状态枚举。
    """

    SUCCESS = "success"
    FAILED = "failed"


class MigrationJobHeader(BaseModel):
    """
    数据库迁移任务公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["migration_job_result"] = MIGRATION_JOB_RESULT_KIND
    schema_version: Literal["1.0"] = MIGRATION_JOB_SCHEMA_VERSION
    operation_name: Literal["database_migration"] = MIGRATION_JOB_OPERATION_NAME


class MigrationJobResultPayload(BaseModel):
    """
    数据库迁移任务结果扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["migration_job_result"] = MIGRATION_JOB_RESULT_KIND
    schema_version: Literal["1.0"] = MIGRATION_JOB_SCHEMA_VERSION
    status: MigrationJobStatus
    exit_code: int = Field(ge=DATABASE_MIGRATION_EXIT_SUCCESS)


MigrationJobDetailUnion = Annotated[
    MigrationJobResultPayload,
    Field(discriminator="kind"),
]


class MigrationJobResult(BaseModel):
    """
    数据库迁移任务结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: MigrationJobHeader
    detail: MigrationJobDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> MigrationJobResult:
        """
        校验迁移任务公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: MigrationJobResult
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("迁移任务 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("迁移任务 schema_version 必须一致。")
        return self


class DatabaseMigrationCli:
    """
    数据库迁移命令行执行器。
    """

    def execute(self) -> MigrationJobResult:
        """
        执行数据库迁移。

        :returns: 迁移任务结果。
        :rtype: MigrationJobResult
        """

        settings = AppSettingsLoader().load()
        logger = AppLoggerFactory().build(settings)
        try:
            AlembicRunner(logger).upgrade_head(settings.runtime.database)
        except Exception:
            logger.exception(MIGRATION_JOB_FAILURE_MESSAGE)
            return self._build_result(
                status=MigrationJobStatus.FAILED,
                exit_code=DATABASE_MIGRATION_EXIT_FAILURE,
            )
        return self._build_result(
            status=MigrationJobStatus.SUCCESS,
            exit_code=DATABASE_MIGRATION_EXIT_SUCCESS,
        )

    def run(self) -> int:
        """
        执行数据库迁移并返回进程退出码。

        :returns: 进程退出码。
        :rtype: int
        """

        return self.execute().detail.exit_code

    def _build_result(
        self,
        *,
        status: MigrationJobStatus,
        exit_code: int,
    ) -> MigrationJobResult:
        """
        构建迁移任务结果。

        :param status: 迁移任务状态。
        :type status: MigrationJobStatus
        :param exit_code: 迁移命令退出码。
        :type exit_code: int
        :returns: 迁移任务结果信封。
        :rtype: MigrationJobResult
        """

        return MigrationJobResult(
            header=MigrationJobHeader(),
            detail=MigrationJobResultPayload(
                status=status,
                exit_code=exit_code,
            ),
        )


if __name__ == "__main__":
    raise SystemExit(DatabaseMigrationCli().run())
