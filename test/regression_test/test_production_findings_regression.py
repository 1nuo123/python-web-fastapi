"""生产 finding 与真实行为测试责任映射回归。"""

from __future__ import annotations

import ast

from src.infrastructure.evidence.regression_catalog_builder import (
    DIRECTED_REGRESSION_CHECKS,
    RegressionCatalogBuilder,
)

EXPECTED_FINDING_COUNT = 26


class TestProductionFindingsRegression:
    """验证每个 finding 唯一映射到全量回归会真实执行的行为测试。"""

    def test_finding_catalog_should_map_each_finding_to_unique_behavior_test(self) -> None:
        """验证映射完整、唯一，且目标测试函数真实存在。"""

        definitions = RegressionCatalogBuilder.list_definitions()
        definition_ids = {definition.finding_id for definition in definitions}
        mapped_responsibilities = {
            (check.test_file, check.testcase_name) for check in DIRECTED_REGRESSION_CHECKS.values()
        }

        assert len(definitions) == EXPECTED_FINDING_COUNT
        assert definition_ids == set(DIRECTED_REGRESSION_CHECKS)
        assert len(mapped_responsibilities) == EXPECTED_FINDING_COUNT
        for check in DIRECTED_REGRESSION_CHECKS.values():
            syntax_tree = ast.parse(check.test_file.read_text(encoding="utf-8"))
            test_functions = {
                node.name
                for node in ast.walk(syntax_tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert check.testcase_name in test_functions
            assert check.key_assertions
