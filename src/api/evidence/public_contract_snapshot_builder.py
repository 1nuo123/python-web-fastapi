"""公开 HTTP、配置、迁移和任务消息契约快照生成模块。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Final, Literal

import rtoml
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from src.api.testing.test_app_factory import TestAppFactory
from src.core.stream_contract.stream_access_contract import StreamAccessTicketEnvelope
from src.core.stream_contract.stream_control_contract import (
    CancelControlDetail,
    PingControlDetail,
    ResumeControlDetail,
    StreamClientControlEnvelope,
    SubscribeControlDetail,
)
from src.core.stream_contract.stream_delivery_contract import (
    StreamBatchEnvelope,
    StreamOperationBindingEnvelope,
)
from src.core.stream_contract.stream_event_contract import (
    StreamEventEnvelope,
    StreamLifecycleDetail,
)
from src.core.stream_contract.stream_runtime_contract import StreamRuntimeEnvelope
from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator

PUBLIC_CONTRACT_SNAPSHOT_SCHEMA_VERSION: Final = "1.0"
PUBLIC_CONTRACT_SNAPSHOT_PATH: Final = Path("docs/evidence/snapshots/public-contract-current.json")
PUBLIC_CONTRACT_BASELINE_PATH: Final = Path("docs/evidence/snapshots/public-contract-baseline.json")
PUBLIC_CONTRACT_COMPARISON_PATH: Final = Path(
    "docs/evidence/snapshots/public-contract-comparison.json"
)
CONFIGURATION_ROOT: Final = Path("config")
MIGRATION_SCRIPT_ROOT: Final = Path("src/infrastructure/persistence/alembic")
TASK_CONTRACT_ROOT: Final = Path("src/core/task_contract")
HTTP_METHODS_WITHOUT_CONTRACT: Final = frozenset({"HEAD", "OPTIONS"})
SHA256_HEX_LENGTH: Final = 64
PUBLIC_STREAM_COMMAND_KIND: Final[Literal["public_stream_command"]] = "public_stream_command"


class PublicStreamCommand(BaseModel):
    """公开控制 Schema 使用的最小强类型订阅命令。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["public_stream_command"] = PUBLIC_STREAM_COMMAND_KIND
    schema_version: Literal["1.0"] = PUBLIC_CONTRACT_SNAPSHOT_SCHEMA_VERSION


PublicStreamControlDetail = Annotated[
    SubscribeControlDetail[PublicStreamCommand]
    | ResumeControlDetail
    | CancelControlDetail
    | PingControlDetail,
    Field(discriminator="kind"),
]


class HttpRouteSnapshot(BaseModel):
    """单条 HTTP 路由冻结事实。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    method: str
    status_codes: tuple[int, ...]
    operation_id: str | None


class ConfigurationKeySnapshot(BaseModel):
    """单个配置文件及其叶子键集合。"""

    model_config = ConfigDict(extra="forbid")

    path: Path
    keys: tuple[str, ...]


class TaskContractSnapshot(BaseModel):
    """任务契约源码摘要。"""

    model_config = ConfigDict(extra="forbid")

    path: Path
    sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)


class StreamContractSchemaSnapshot(BaseModel):
    """流式公开契约 JSON Schema 快照。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    json_schema_document: str
    sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)


class PublicContractSnapshot(BaseModel):
    """机器可比对公开契约快照。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = PUBLIC_CONTRACT_SNAPSHOT_SCHEMA_VERSION
    generated_at: datetime
    code_baseline: str
    openapi_sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    openapi_document: dict[str, JsonValue]
    routes: tuple[HttpRouteSnapshot, ...]
    configuration: tuple[ConfigurationKeySnapshot, ...]
    migration_heads: tuple[str, ...]
    task_contracts: tuple[TaskContractSnapshot, ...]
    stream_contracts: tuple[StreamContractSchemaSnapshot, ...] = ()


class PublicContractComparison(BaseModel):
    """冻结基线与当前公开契约的机器差异结果。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = PUBLIC_CONTRACT_SNAPSHOT_SCHEMA_VERSION
    baseline_path: Path
    current_path: Path
    compatible: bool
    changed_sections: tuple[str, ...]


class PublicContractSnapshotBuilder:
    """从当前可执行应用和结构化配置生成公开契约快照。"""

    @classmethod
    def build(cls) -> PublicContractSnapshot:
        """生成当前公开契约快照。"""

        app = TestAppFactory().create()
        try:
            openapi_document = app.openapi()
            openapi_payload = json.dumps(
                openapi_document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            routes = cls._build_route_snapshots(openapi_document)
            return PublicContractSnapshot(
                generated_at=datetime.now(UTC),
                code_baseline=CodeBaselineCalculator.calculate(),
                openapi_sha256=sha256(openapi_payload.encode("utf-8")).hexdigest(),
                openapi_document=openapi_document,
                routes=routes,
                configuration=cls._build_configuration_snapshots(),
                migration_heads=tuple(
                    sorted(ScriptDirectory(str(MIGRATION_SCRIPT_ROOT)).get_heads())
                ),
                task_contracts=tuple(
                    TaskContractSnapshot(
                        path=path,
                        sha256=sha256(path.read_bytes()).hexdigest(),
                    )
                    for path in sorted(TASK_CONTRACT_ROOT.glob("*.py"))
                    if path.name != "__init__.py"
                ),
                stream_contracts=cls._build_stream_contract_snapshots(),
            )
        finally:
            app.state.container.resource_mount.shutdown()

    @classmethod
    def save(
        cls,
        path: Path = PUBLIC_CONTRACT_SNAPSHOT_PATH,
        *,
        promote_baseline: bool = False,
    ) -> tuple[Path, Path, Path]:
        """保存当前快照、冻结基线和机器差异结果。"""

        snapshot = cls.build()
        cls._save_model(path, snapshot.model_dump_json(indent=2))
        if promote_baseline or not PUBLIC_CONTRACT_BASELINE_PATH.is_file():
            cls._save_model(
                PUBLIC_CONTRACT_BASELINE_PATH,
                snapshot.model_dump_json(indent=2),
            )
        baseline = PublicContractSnapshot.model_validate_json(
            PUBLIC_CONTRACT_BASELINE_PATH.read_text(encoding="utf-8")
        )
        sections = {
            "openapi": baseline.openapi_document == snapshot.openapi_document,
            "routes": baseline.routes == snapshot.routes,
            "configuration": baseline.configuration == snapshot.configuration,
            "migration_heads": baseline.migration_heads == snapshot.migration_heads,
            "task_contracts": baseline.task_contracts == snapshot.task_contracts,
            "stream_contracts": baseline.stream_contracts == snapshot.stream_contracts,
        }
        comparison = PublicContractComparison(
            baseline_path=PUBLIC_CONTRACT_BASELINE_PATH,
            current_path=path,
            compatible=all(sections.values()),
            changed_sections=tuple(name for name, unchanged in sections.items() if not unchanged),
        )
        cls._save_model(
            PUBLIC_CONTRACT_COMPARISON_PATH,
            comparison.model_dump_json(indent=2),
        )
        return path, PUBLIC_CONTRACT_BASELINE_PATH, PUBLIC_CONTRACT_COMPARISON_PATH

    @classmethod
    def _build_configuration_snapshots(cls) -> tuple[ConfigurationKeySnapshot, ...]:
        """使用 TOML 解析器收集全部配置叶子键。"""

        return tuple(
            ConfigurationKeySnapshot(
                path=path,
                keys=tuple(sorted(cls._flatten_keys(rtoml.load(path)))),
            )
            for path in sorted(CONFIGURATION_ROOT.rglob("*.toml"))
        )

    @classmethod
    def _flatten_keys(cls, values: dict[str, object], prefix: str = "") -> set[str]:
        """递归展开结构化 TOML 映射的叶子键。"""

        keys: set[str] = set()
        for key, value in values.items():
            qualified_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.update(cls._flatten_keys(value, qualified_key))
            else:
                keys.add(qualified_key)
        return keys

    @classmethod
    def _build_stream_contract_snapshots(cls) -> tuple[StreamContractSchemaSnapshot, ...]:
        """生成流事件、控制、绑定和运行时 JSON Schema。"""

        adapters = (
            (
                "stream_event",
                TypeAdapter(StreamEventEnvelope[StreamLifecycleDetail]),
            ),
            (
                "stream_client_control",
                TypeAdapter(StreamClientControlEnvelope[PublicStreamControlDetail]),
            ),
            ("stream_operation_binding", TypeAdapter(StreamOperationBindingEnvelope)),
            ("stream_batch", TypeAdapter(StreamBatchEnvelope[StreamLifecycleDetail])),
            ("stream_access_ticket", TypeAdapter(StreamAccessTicketEnvelope)),
            ("stream_runtime", TypeAdapter(StreamRuntimeEnvelope)),
        )
        snapshots: list[StreamContractSchemaSnapshot] = []
        for name, adapter in adapters:
            json_schema_document = json.dumps(
                adapter.json_schema(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            snapshots.append(
                StreamContractSchemaSnapshot(
                    name=name,
                    json_schema_document=json_schema_document,
                    sha256=sha256(json_schema_document.encode("utf-8")).hexdigest(),
                )
            )
        return tuple(snapshots)

    @staticmethod
    def _build_route_snapshots(
        openapi_document: dict[str, JsonValue],
    ) -> tuple[HttpRouteSnapshot, ...]:
        """从 OpenAPI 路径对象提取方法、状态码和操作标识。"""

        paths_value = openapi_document.get("paths")
        if not isinstance(paths_value, dict):
            return ()
        routes: list[HttpRouteSnapshot] = []
        for route_path, path_item in paths_value.items():
            if not isinstance(route_path, str) or not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                normalized_method = method.upper()
                if normalized_method in HTTP_METHODS_WITHOUT_CONTRACT or not isinstance(
                    operation, dict
                ):
                    continue
                responses = operation.get("responses")
                status_codes = tuple(
                    sorted(
                        int(status_code)
                        for status_code in responses
                        if isinstance(status_code, str) and status_code.isdigit()
                    )
                    if isinstance(responses, dict)
                    else (HTTPStatus.OK,)
                )
                operation_id = operation.get("operationId")
                routes.append(
                    HttpRouteSnapshot(
                        path=route_path,
                        method=normalized_method,
                        status_codes=status_codes or (HTTPStatus.OK,),
                        operation_id=operation_id if isinstance(operation_id, str) else None,
                    )
                )
        return tuple(sorted(routes, key=lambda item: (item.path, item.method)))

    @staticmethod
    def _save_model(path: Path, payload: str) -> None:
        """原子保存结构化快照。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(payload + "\n", encoding="utf-8")
        temporary_path.replace(path)
