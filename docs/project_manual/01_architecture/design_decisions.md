# 架构决策

## 1. 文档目的
记录当前代码能确认的架构决策和原因，避免把历史执行方案误认为当前事实。

**最后更新范围**：覆盖当前代码中可确认的装配、契约、响应、运行时和测试决策。

## 2. 适用读者
- 新人开发者
- 后端开发者
- 测试维护者
- 运维部署人员
- 安全审查人员

## 3. 关联源码
| 路径 | 作用 |
| --- | --- |
| `src/main.py` | ASGI 入口。 |
| `src/api/asgi_entry.py` | `AsgiApplicationFactory`。 |
| `src/api/fastapi_app_assembler.py` | `FastApiAppAssembler`。 |
| `src/infrastructure/fastapi_route_composer.py` | Web 模块路由挂载。 |
| `src/infrastructure/fastapi_lifespan_orchestrator.py` | 生命周期上下文。 |
| `src/infrastructure/resource_mount` | 运行时资源启动、释放和访问器刷新。 |
| `src/infrastructure/shared_resource_mount.py` | 运行时资源门面。 |
| `src/core/http_contract/response_envelope_contract.py` | 响应契约。 |

## 4. 核心结论
- 决策 1：入口薄化，真实装配集中在 `FastApiAppAssembler`。
- 决策 2：Web 模块集中清单管理，`WebModuleManifestRegistry` 声明模块和后台边界策略，`WebBundleCatalog` 加载 provider，`FastApiRouteComposer` 只挂载配置启用的 `WebBundle.router`，避免路由散落注册。
- 决策 3：HTTP 响应统一使用 `ResponseEnvelope`。
- 决策 4：运行时资源由 `SharedResourceMount` 提供稳定门面，具体启动、释放和访问器刷新分别由 `RuntimeResourceBootstrapper`、`RuntimeResourceReleaser`、`RuntimeAccessorRefresher` 协作完成；路由不直接创建外部连接。
- 决策 5：配置热更新通过 `SettingsApplyTransaction` 切换候选 HTTP 资源、任务运行时、鉴权依赖和日志级别；失败时回滚旧快照并记录配置安全事件。
- 决策 6：生产环境安全配置由 `SettingsSecurityValidator` 做强约束。
- 决策 7：中间件顺序由 `FastApiMiddlewarePlan.build_bindings` 统一生成，装配器以反向 `app.add_middleware` 绑定，确保计划列表中的请求作用域、载荷防护、认证、限流、安全头、耗时探针和可选访问日志按预期进入请求链路；Prometheus HTTP 指标中间件属于指标配置开启后的额外外层。

## 5. 结构说明
本文件不是 ADR 历史库，而是当前说明书中的决策摘要；新增正式 ADR 可使用 `templates/decision_record_template.md`。

## 6. 工作流程
非流程类文档：决策条目按当前源码可确认内容维护。

## 7. 关键实现
| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `WebModuleManifestRegistry.validate_admin_boundary_authorization` | `src/api/web_module_manifest.py` | 校验后台模块边界策略。 |
| `FastApiRouteComposer.compose` | `src/infrastructure/fastapi_route_composer.py` | 按启用模块和 API 前缀挂载路由。 |
| `SettingsSecurityValidator` | `src/infrastructure/settings/settings_security_validator.py` | 生产安全配置校验。 |
| `SettingsApplyTransaction` | `src/infrastructure/settings/settings_apply_transaction.py` | 配置应用提交与回滚。 |
| `ResponseEnvelopeFactory` | `src/core/http_contract/response_envelope_contract.py` | 统一响应构造。 |
| `RuntimeResourceBootstrapper` / `RuntimeResourceReleaser` | `src/infrastructure/resource_mount` | 拆分资源启动与释放流程。 |

## 8. 如何修改或扩展
1. 新增架构决策时写清背景、决策、原因和影响。
2. 如果决策涉及代码约束，补测试保护。
3. 大型决策可复制 ADR 模板到合适目录后从本文件链接。

## 9. 测试覆盖
| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | 后台模块边界策略校验。 |
| unit | `test/unit_test/test_settings_security_unit.py` | 生产安全配置校验。 |
| contract | `test/contract_test/test_http_contract.py` | 统一响应契约。 |

## 10. 常见问题
- 待确认：是否需要将历史执行方案中的决策迁移为正式 ADR，需维护者选择。

## 11. 维护备注
决策变更时同步检查对应代码、测试和 README 推荐路径。



## 12. 相关文档
- [项目文档总览](../README.md)
- [ADR 模板](../templates/decision_record_template.md)
