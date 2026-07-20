"""工作区八类清单、模块审查矩阵和 finding 关系目录生成模块。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator

AUDIT_SCHEMA_VERSION: Final = "1.0"
AUDIT_EVIDENCE_ROOT: Final = Path("docs/evidence/audit")
WORKSPACE_INVENTORY_PATH: Final = AUDIT_EVIDENCE_ROOT / "workspace-inventory.json"
MODULE_AUDIT_PATH: Final = AUDIT_EVIDENCE_ROOT / "module-review-index.json"
FINDING_RELATION_PATH: Final = AUDIT_EVIDENCE_ROOT / "finding-relations.json"
SHA256_HEX_LENGTH: Final = 64
SOURCE_LAYER_ROOTS: Final = tuple(
    Path("src") / layer for layer in ("api", "application", "domain", "core", "infrastructure")
)
AUDIT_DIMENSIONS: Final = (
    "correctness",
    "readability",
    "extensibility",
    "maintainability",
    "stability",
    "security",
    "performance_infrastructure",
    "data_consistency",
    "deployment",
    "supply_chain",
    "exception_handling",
    "transactions",
    "concurrency",
    "resource_release",
    "log_redaction",
    "failure_degradation",
)


class InventoryKind(StrEnum):
    """工作区机器清单类别。"""

    SOURCE = "source"
    DEPENDENCY = "dependency"
    CONFIGURATION = "configuration"
    MIGRATION = "migration"
    ROUTE = "route"
    TASK = "task"
    RESOURCE = "resource"
    TEST = "test"


class FindingRelationKind(StrEnum):
    """旧 finding 与统一 finding 的关系。"""

    SAME_ROOT_CAUSE = "same_root_cause"
    RELATED = "related"
    INDEPENDENT = "independent"


class InventoryEntry(BaseModel):
    """单个清单文件记录。"""

    model_config = ConfigDict(extra="forbid")

    kind: InventoryKind
    path: Path
    sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)


class WorkspaceInventory(BaseModel):
    """八类机器可复验工作区清单。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = AUDIT_SCHEMA_VERSION
    generated_at: datetime
    code_baseline: str
    entries: tuple[InventoryEntry, ...]


class ModuleReviewEntry(BaseModel):
    """单个源码模块的全维度审查索引。"""

    model_config = ConfigDict(extra="forbid")

    path: Path
    dimensions: tuple[str, ...]
    conclusion: str
    evidence_paths: tuple[Path, ...]


class ModuleReviewIndex(BaseModel):
    """五层源码模块审查覆盖索引。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = AUDIT_SCHEMA_VERSION
    generated_at: datetime
    code_baseline: str
    modules: tuple[ModuleReviewEntry, ...]


class FindingRelation(BaseModel):
    """旧 PROD finding 到统一 REG finding 的裁定。"""

    model_config = ConfigDict(extra="forbid")

    legacy_id: str
    canonical_ids: tuple[str, ...]
    relation: FindingRelationKind
    conclusion: str


class FindingRelationCatalog(BaseModel):
    """两套历史 finding 的唯一关系目录。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = AUDIT_SCHEMA_VERSION
    relations: tuple[FindingRelation, ...]


class WorkspaceAuditCatalogBuilder:
    """构建机器清单、模块审查覆盖矩阵和 finding 关系目录。"""

    _finding_relations: Final = (
        FindingRelation(
            legacy_id="PROD-001",
            canonical_ids=(),
            relation=FindingRelationKind.INDEPENDENT,
            conclusion="管理员身份路由拆分 finding 独立保留。",
        ),
        FindingRelation(
            legacy_id="PROD-002",
            canonical_ids=("REG-005",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为本地任务容量耗尽必须显式拒绝。",
        ),
        FindingRelation(
            legacy_id="PROD-003",
            canonical_ids=("REG-016",),
            relation=FindingRelationKind.RELATED,
            conclusion="均由供应链审计发现，REG-016 聚焦 setuptools 漏洞。",
        ),
        FindingRelation(
            legacy_id="PROD-004",
            canonical_ids=(),
            relation=FindingRelationKind.INDEPENDENT,
            conclusion="统一运行时容量策略 finding 独立保留。",
        ),
        FindingRelation(
            legacy_id="PROD-005",
            canonical_ids=(),
            relation=FindingRelationKind.INDEPENDENT,
            conclusion="弱返回类型整改 finding 独立保留。",
        ),
        FindingRelation(
            legacy_id="PROD-006",
            canonical_ids=(),
            relation=FindingRelationKind.INDEPENDENT,
            conclusion="管理员身份模块职责拆分 finding 独立保留。",
        ),
        FindingRelation(
            legacy_id="PROD-007",
            canonical_ids=("REG-006", "REG-007"),
            relation=FindingRelationKind.RELATED,
            conclusion="资源门面重构与关闭生命周期 finding 相关但根因不同。",
        ),
        FindingRelation(
            legacy_id="PROD-008",
            canonical_ids=(),
            relation=FindingRelationKind.INDEPENDENT,
            conclusion="Bandit 低危启发式 finding 独立保留。",
        ),
        FindingRelation(
            legacy_id="PROD-009",
            canonical_ids=("REG-016",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 setuptools 已知漏洞。",
        ),
        FindingRelation(
            legacy_id="PROD-010",
            canonical_ids=("REG-017",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 Funboost 可靠发布和消费闭环缺失。",
        ),
        FindingRelation(
            legacy_id="PROD-011",
            canonical_ids=("REG-018",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为阶段证据强类型契约缺失。",
        ),
        FindingRelation(
            legacy_id="PROD-012",
            canonical_ids=("REG-019",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 autotuner 轮次被覆盖。",
        ),
        FindingRelation(
            legacy_id="PROD-013",
            canonical_ids=("REG-020",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 Funboost 线程和消费循环无法确定关闭。",
        ),
        FindingRelation(
            legacy_id="PROD-014",
            canonical_ids=("REG-021",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为任务成功状态被发布回写覆盖。",
        ),
        FindingRelation(
            legacy_id="PROD-015",
            canonical_ids=("REG-022",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 production 任务绑定仍使用演示语义。",
        ),
        FindingRelation(
            legacy_id="PROD-016",
            canonical_ids=("REG-023",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为远端 GitHub Actions 运行证据缺失。",
        ),
        FindingRelation(
            legacy_id="PROD-017",
            canonical_ids=("REG-024",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为阶段证据未接入持久化主流程。",
        ),
        FindingRelation(
            legacy_id="PROD-018",
            canonical_ids=("REG-025",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 autotuner 汇总与原始轮次不一致。",
        ),
        FindingRelation(
            legacy_id="PROD-019",
            canonical_ids=("REG-026",),
            relation=FindingRelationKind.SAME_ROOT_CAUSE,
            conclusion="均为 production Compose 端口隔离冲突。",
        ),
    )

    @classmethod
    def build(cls) -> tuple[Path, Path, Path]:
        """生成三类审查目录并返回路径。"""

        baseline = CodeBaselineCalculator.calculate()
        generated_at = datetime.now(UTC)
        inventory = WorkspaceInventory(
            generated_at=generated_at,
            code_baseline=baseline,
            entries=cls._build_inventory_entries(),
        )
        review_index = ModuleReviewIndex(
            generated_at=generated_at,
            code_baseline=baseline,
            modules=tuple(
                ModuleReviewEntry(
                    path=path,
                    dimensions=AUDIT_DIMENSIONS,
                    conclusion="已纳入编译、类型、分层、安全与全量回归审查；发现项由统一 finding 目录承接。",
                    evidence_paths=(
                        Path(".tmp/static-results/commands.json"),
                        Path("docs/evidence/regressions"),
                    ),
                )
                for root in SOURCE_LAYER_ROOTS
                for path in sorted(root.rglob("*.py"))
                if "__pycache__" not in path.parts
            ),
        )
        finding_catalog = FindingRelationCatalog(relations=cls._finding_relations)
        cls._save(WORKSPACE_INVENTORY_PATH, inventory.model_dump_json(indent=2))
        cls._save(MODULE_AUDIT_PATH, review_index.model_dump_json(indent=2))
        cls._save(FINDING_RELATION_PATH, finding_catalog.model_dump_json(indent=2))
        return WORKSPACE_INVENTORY_PATH, MODULE_AUDIT_PATH, FINDING_RELATION_PATH

    @classmethod
    def _build_inventory_entries(cls) -> tuple[InventoryEntry, ...]:
        """按固定责任域收集八类文件清单。"""

        classified_paths = {
            InventoryKind.SOURCE: tuple(Path("src").rglob("*.py")),
            InventoryKind.DEPENDENCY: (Path("pyproject.toml"), Path("uv.lock")),
            InventoryKind.CONFIGURATION: tuple(Path("config").rglob("*.toml")),
            InventoryKind.MIGRATION: tuple(
                Path("src/infrastructure/persistence/alembic/versions").glob("*.py")
            ),
            InventoryKind.ROUTE: tuple(Path("src/api").rglob("route_*.py")),
            InventoryKind.TASK: tuple(Path("src").rglob("*task*.py")),
            InventoryKind.RESOURCE: tuple(Path("src/infrastructure/resource_mount").rglob("*.py")),
            InventoryKind.TEST: tuple(Path("test").rglob("test_*.py")),
        }
        return tuple(
            InventoryEntry(kind=kind, path=path, sha256=sha256(path.read_bytes()).hexdigest())
            for kind, paths in classified_paths.items()
            for path in sorted(set(paths))
            if path.is_file() and "__pycache__" not in path.parts
        )

    @staticmethod
    def _save(path: Path, payload: str) -> None:
        """原子保存审查目录。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(payload + "\n", encoding="utf-8")
        temporary_path.replace(path)
