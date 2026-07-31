# FastAPI Web Skeleton 项目说明书

## 1. 文档目的
这是 `/docs/project_manual` 的唯一入口，用于把当前 FastAPI 后端项目的架构、运行时、API、数据、部署、测试和维护资料串成可导航说明书。

**最后更新范围**：基于当前代码中的 `src`、`config`、`test`、`Dockerfile`、`compose.yml`、`compose.production.yml`、`pyproject.toml` 生成；历史执行方案只作为关联资料，不作为当前实现事实。

**文档状态**：`current`。82 份项目手册的强类型 `DocumentationRecord` 位于 `docs/evidence/documentation/`，统一索引为 `docs/evidence/phase_evidence_index.json`。

**最终回归**：真实依赖全量回归 797 passed、225 warnings，无 skip/xfail；总体覆盖率 90.7986%，四个关键域均不低于 90%。阶段总览见 [生产级代码全量审查与整改硬迁移总览](../2026_7_13_生产级代码全量审查与整改硬迁移拆解/生产级代码全量审查与整改硬迁移总览.md)。

**finding 状态**：`REGRESSION_STATUS_COUNTS: open=0;fixed=26;verified=0;rejected=0`。当前代码基线重新生成证据后，26 项均保持 `fixed`；根因修复、当前定向测试和同基线全量回归均已通过。这是证据成熟度差异，不是未关闭 P1。当前允许进入业务开发，发布阶段仍需执行 [生产级整改最终收口结论与执行清单](10_maintenance/production_closure_checklist.md)。

## 2. 适用读者
- 新人开发者
- 后端开发者
- 测试维护者
- 运维部署人员
- 安全审查人员

## 3. 关联源码
| 路径 | 作用 |
| --- | --- |
| `src/main.py` | ASGI 应用入口，调用 `src.api.asgi_entry.create_app`。 |
| `src/api` | HTTP route、contract、Web 模块 manifest 与 bundle catalog。 |
| `src/application` | 用例层、后台管理用例和应用端口。 |
| `src/cli` | 运维脚本入口，目前包含数据库迁移和初始化管理员相关命令。 |
| `src/core` | 核心契约，覆盖 auth/cache/http/task/security/logging/persistence/observability。 |
| `src/infrastructure` | FastAPI 装配、配置、持久化、缓存、任务、日志、安全、可观测性和资源生命周期实现。 |
| `config` | app/module/runtime TOML 配置。 |
| `test` | unit/contract/boundary/interface/exception/path/initialization/class_inheritance/convention_usage/integration/performance 分层测试。 |
| `docs/evidence/phase_evidence_index.json` | TestRun、Regression、Documentation 三类生产整改证据统一索引。 |

## 4. 项目一句话说明
本项目是一个 Python 3.11+ FastAPI 后端骨架，围绕统一响应信封、模块化路由、应用用例端口、可替换运行时资源和分层测试构建。

## 5. 推荐阅读路径
1. 新接手项目先读 [项目概览](00_project_overview/project_summary.md)、[快速启动](00_project_overview/quick_start.md)、[仓库地图](00_project_overview/repository_map.md)。
2. 理解主链路读 [架构总览](01_architecture/architecture_overview.md)、[请求生命周期](01_architecture/request_lifecycle.md)、[FastAPI 应用装配](02_backend/fastapi_app_assembly.md)。
3. 写业务接口读 [API 模块注册](02_backend/api_module_registration.md)、[路由契约模式](02_backend/route_contract_pattern.md)、[新增接口指南](09_development_guide/adding_new_api.md)。
4. 运维部署读 [配置文件](07_configuration_deployment/configuration_files.md)、[环境变量](07_configuration_deployment/environment_variables.md)、[Docker 部署](07_configuration_deployment/docker_deployment.md)。
5. 排查问题读 [故障排查](10_maintenance/troubleshooting.md)、[常见失败模式](10_maintenance/common_failure_modes.md)。

## 6. 文档地图
| 主题 | 入口 |
| --- | --- |
| 项目概览 | [00_project_overview/project_summary.md](00_project_overview/project_summary.md) |
| 快速启动 | [00_project_overview/quick_start.md](00_project_overview/quick_start.md) |
| 仓库地图 | [00_project_overview/repository_map.md](00_project_overview/repository_map.md) |
| 术语表 | [00_project_overview/glossary.md](00_project_overview/glossary.md) |
| 架构总览 | [01_architecture/architecture_overview.md](01_architecture/architecture_overview.md) |
| 后端装配 | [02_backend/fastapi_app_assembly.md](02_backend/fastapi_app_assembly.md) |
| 应用与领域 | [03_application_domain/application_usecases.md](03_application_domain/application_usecases.md) |
| 基础设施 | [04_infrastructure/configuration_system.md](04_infrastructure/configuration_system.md) |
| API 参考 | [05_api_reference/api_overview.md](05_api_reference/api_overview.md) |
| 数据与迁移 | [06_data/database_overview.md](06_data/database_overview.md) |
| 配置与部署 | [07_configuration_deployment/configuration_files.md](07_configuration_deployment/configuration_files.md) |
| 测试体系 | [08_testing/testing_strategy.md](08_testing/testing_strategy.md) |
| 本轮生产审查 | [../2026_7_13_生产级代码审查回归报告.md](../2026_7_13_生产级代码审查回归报告.md) |
| 开发指南 | [09_development_guide/adding_new_api.md](09_development_guide/adding_new_api.md) |
| 维护指南 | [10_maintenance/troubleshooting.md](10_maintenance/troubleshooting.md) |
| 模板 | [templates/module_doc_template.md](templates/module_doc_template.md) |

## 7. 按角色导航
- 新人开发者：[项目概览](00_project_overview/project_summary.md)、[快速启动](00_project_overview/quick_start.md)、[术语表](00_project_overview/glossary.md)。
- 后端开发者：[分层架构](01_architecture/layered_architecture.md)、[应用用例](03_application_domain/application_usecases.md)、[新增接口](09_development_guide/adding_new_api.md)。
- 测试维护者：[测试策略](08_testing/testing_strategy.md)、[测试目录地图](08_testing/test_directory_map.md)、[如何新增测试](08_testing/how_to_add_tests.md)。
- 运维部署人员：[配置文件](07_configuration_deployment/configuration_files.md)、[Docker 部署](07_configuration_deployment/docker_deployment.md)、[运维检查清单](07_configuration_deployment/operations_checklist.md)。
- 安全审查人员：[鉴权与授权](04_infrastructure/authentication_and_authorization.md)、[安全防护](04_infrastructure/security_protection.md)、[安全维护](10_maintenance/security_maintenance.md)。

## 8. 高频任务入口
- 如何启动项目：[快速启动](00_project_overview/quick_start.md)、[本地开发](07_configuration_deployment/local_development.md)。
- 如何新增接口：[新增 API](09_development_guide/adding_new_api.md)、[API 模块注册](02_backend/api_module_registration.md)。
- 如何新增用例：[新增用例](09_development_guide/adding_new_usecase.md)、[应用用例](03_application_domain/application_usecases.md)。
- 如何新增配置：[新增配置](09_development_guide/adding_new_config.md)、[配置系统](04_infrastructure/configuration_system.md)。
- 如何新增数据库迁移：[新增迁移](09_development_guide/adding_new_migration.md)、[Alembic 迁移](06_data/alembic_migrations.md)。
- 如何新增测试：[如何新增测试](08_testing/how_to_add_tests.md)。
- 如何排查启动失败：[故障排查](10_maintenance/troubleshooting.md)、[常见失败模式](10_maintenance/common_failure_modes.md)。

## 9. 关联已有文档
- [技术选型](../技术选型.md)
- [编码规范](../standard/编码规范.md)
- [测试规范](../standard/测试规范.md)
- [命名规范](../standard/命名规范.md)
- [Docker 启动运行指南](../Docker启动运行指南.md)
- [security_protection_runtime 说明](../security_protection_runtime说明.md)
- [observability Grafana Prometheus 接入说明](../observability_grafana_prometheus接入说明.md)
- [2026-07-13 生产级代码审查回归报告](../2026_7_13_生产级代码审查回归报告.md)
- [2026-07-13 真实失败根因回归记录](../2026_7_13_真实失败根因回归记录.md)

## 10. 全量文档索引
- [00_project_overview/project_summary.md](00_project_overview/project_summary.md)
- [00_project_overview/quick_start.md](00_project_overview/quick_start.md)
- [00_project_overview/repository_map.md](00_project_overview/repository_map.md)
- [00_project_overview/glossary.md](00_project_overview/glossary.md)
- [01_architecture/architecture_overview.md](01_architecture/architecture_overview.md)
- [01_architecture/layered_architecture.md](01_architecture/layered_architecture.md)
- [01_architecture/request_lifecycle.md](01_architecture/request_lifecycle.md)
- [01_architecture/dependency_direction.md](01_architecture/dependency_direction.md)
- [01_architecture/runtime_resource_lifecycle.md](01_architecture/runtime_resource_lifecycle.md)
- [01_architecture/design_decisions.md](01_architecture/design_decisions.md)
- [02_backend/fastapi_app_assembly.md](02_backend/fastapi_app_assembly.md)
- [02_backend/api_module_registration.md](02_backend/api_module_registration.md)
- [02_backend/route_contract_pattern.md](02_backend/route_contract_pattern.md)
- [02_backend/middleware_chain.md](02_backend/middleware_chain.md)
- [02_backend/exception_handling.md](02_backend/exception_handling.md)
- [02_backend/response_envelope.md](02_backend/response_envelope.md)
- [03_application_domain/application_usecases.md](03_application_domain/application_usecases.md)
- [03_application_domain/application_ports.md](03_application_domain/application_ports.md)
- [03_application_domain/domain_model_and_constants.md](03_application_domain/domain_model_and_constants.md)
- [03_application_domain/admin_business_capabilities.md](03_application_domain/admin_business_capabilities.md)
- [04_infrastructure/configuration_system.md](04_infrastructure/configuration_system.md)
- [04_infrastructure/persistence_and_migrations.md](04_infrastructure/persistence_and_migrations.md)
- [04_infrastructure/authentication_and_authorization.md](04_infrastructure/authentication_and_authorization.md)
- [04_infrastructure/security_protection.md](04_infrastructure/security_protection.md)
- [04_infrastructure/cache_runtime.md](04_infrastructure/cache_runtime.md)
- [04_infrastructure/task_runtime.md](04_infrastructure/task_runtime.md)
- [04_infrastructure/logging_runtime.md](04_infrastructure/logging_runtime.md)
- [04_infrastructure/observability.md](04_infrastructure/observability.md)
- [04_infrastructure/distributed_lock.md](04_infrastructure/distributed_lock.md)
- [04_infrastructure/outbound_http_safety.md](04_infrastructure/outbound_http_safety.md)
- [05_api_reference/api_overview.md](05_api_reference/api_overview.md)
- [05_api_reference/auth_api.md](05_api_reference/auth_api.md)
- [05_api_reference/health_api.md](05_api_reference/health_api.md)
- [05_api_reference/admin_task_api.md](05_api_reference/admin_task_api.md)
- [05_api_reference/admin_settings_api.md](05_api_reference/admin_settings_api.md)
- [05_api_reference/admin_log_api.md](05_api_reference/admin_log_api.md)
- [05_api_reference/admin_identity_api.md](05_api_reference/admin_identity_api.md)
- [05_api_reference/admin_audit_api.md](05_api_reference/admin_audit_api.md)
- [05_api_reference/security_protection_api.md](05_api_reference/security_protection_api.md)
- [05_api_reference/system_overview_api.md](05_api_reference/system_overview_api.md)
- [06_data/database_overview.md](06_data/database_overview.md)
- [06_data/orm_models.md](06_data/orm_models.md)
- [06_data/alembic_migrations.md](06_data/alembic_migrations.md)
- [06_data/repository_pattern.md](06_data/repository_pattern.md)
- [06_data/transaction_boundary.md](06_data/transaction_boundary.md)
- [07_configuration_deployment/configuration_files.md](07_configuration_deployment/configuration_files.md)
- [07_configuration_deployment/environment_variables.md](07_configuration_deployment/environment_variables.md)
- [07_configuration_deployment/local_development.md](07_configuration_deployment/local_development.md)
- [07_configuration_deployment/docker_deployment.md](07_configuration_deployment/docker_deployment.md)
- [07_configuration_deployment/production_deployment.md](07_configuration_deployment/production_deployment.md)
- [07_configuration_deployment/operations_checklist.md](07_configuration_deployment/operations_checklist.md)
- [08_testing/testing_strategy.md](08_testing/testing_strategy.md)
- [08_testing/test_directory_map.md](08_testing/test_directory_map.md)
- [08_testing/unit_tests.md](08_testing/unit_tests.md)
- [08_testing/contract_tests.md](08_testing/contract_tests.md)
- [08_testing/interface_tests.md](08_testing/interface_tests.md)
- [08_testing/integration_tests.md](08_testing/integration_tests.md)
- [08_testing/boundary_exception_path_tests.md](08_testing/boundary_exception_path_tests.md)
- [08_testing/how_to_add_tests.md](08_testing/how_to_add_tests.md)
- [09_development_guide/coding_conventions.md](09_development_guide/coding_conventions.md)
- [09_development_guide/naming_conventions.md](09_development_guide/naming_conventions.md)
- [09_development_guide/adding_new_api.md](09_development_guide/adding_new_api.md)
- [09_development_guide/adding_new_usecase.md](09_development_guide/adding_new_usecase.md)
- [09_development_guide/adding_new_runtime_component.md](09_development_guide/adding_new_runtime_component.md)
- [09_development_guide/adding_new_config.md](09_development_guide/adding_new_config.md)
- [09_development_guide/adding_new_migration.md](09_development_guide/adding_new_migration.md)
- [09_development_guide/review_checklist.md](09_development_guide/review_checklist.md)
- [10_maintenance/troubleshooting.md](10_maintenance/troubleshooting.md)
- [10_maintenance/common_failure_modes.md](10_maintenance/common_failure_modes.md)
- [10_maintenance/security_maintenance.md](10_maintenance/security_maintenance.md)
- [10_maintenance/performance_notes.md](10_maintenance/performance_notes.md)
- [10_maintenance/documentation_maintenance.md](10_maintenance/documentation_maintenance.md)
- [10_maintenance/changelog.md](10_maintenance/changelog.md)
- [10_maintenance/production_closure_checklist.md](10_maintenance/production_closure_checklist.md)
- [生产级代码审查回归报告](../2026_7_13_生产级代码审查回归报告.md)
- [生产性能真实验证报告](../2026_7_13_生产性能真实验证报告.md)
- [真实失败根因回归记录](../2026_7_13_真实失败根因回归记录.md)
- [templates/module_doc_template.md](templates/module_doc_template.md)
- [templates/api_doc_template.md](templates/api_doc_template.md)
- [templates/runtime_component_template.md](templates/runtime_component_template.md)
- [templates/usecase_doc_template.md](templates/usecase_doc_template.md)
- [templates/database_table_template.md](templates/database_table_template.md)
- [templates/test_doc_template.md](templates/test_doc_template.md)
- [templates/decision_record_template.md](templates/decision_record_template.md)
