# 架构决策

## 1. 这是什么

当前代码可直接验证的关键架构决策清单：每条含背景、决策、原因与代码锚点。它不是历史 ADR 库（正式 ADR 用 `templates/decision_record_template.md`），而是"为什么代码长这样"的速查表。

**最后更新范围**：基于当前源码可确认的装配、契约、响应、运行时、安全与测试决策，共 12 条。

## 2. 决策清单

### D1 入口薄化，装配集中于组合根

`src/main.py` 只有 `app = create_app()`；全部组装在 `FastApiAppAssembler`。
**原因**：单一组装点使依赖关系可审计、测试可整体替换（`TestAppFactory` 用同一装配器注入 SQLite 引擎工厂与显式任务绑定）；避免 import 副作用式初始化。

### D2 Web 模块集中清单 + 双向校验

`WebModuleManifestRegistry` 声明 9 个模块（provider import 路径、route tags、后台边界策略）；`WebBundleCatalog` 动态装载并校验 provider 输出与 manifest 一致；`FastApiRouteComposer` 只挂载 `app.modules.enabled` 中的模块，且启用了但没挂上的模块名直接抛错。
**原因**：路由注册不散落；配置错误在启动即暴露；模块启停变成纯配置行为。

### D3 统一响应信封（含全部异常路径）

一切响应都是 `ResponseEnvelope{header{code,message,request_id,trace_id},data}`；异常出口（presenter、payload guard、认证中间件、限流中间件）全部复用同一工厂。
**原因**：客户端只需一种解析逻辑；`request_id/trace_id` 全链路可关联；错误码目录（`SuccessCode`/`CoreErrorCode`/`AuthErrorCode`/`AdminIdentityErrorCode`）成为对外稳定契约。

### D4 header+detail 契约信封与判别联合

配置块（请求执行、出站 HTTP、安全、指标、日志、任务/消息后端、任务注册、告警规则）与事件（日志事件、安全事件、资源操作）统一 `header{kind,schema_version} + detail(kind 判别联合)`，`model_validator` 校验两侧一致，全模型 `extra="forbid"`。
**原因**：结构演进只加新 detail 类型；拼错键/版本漂移在启动或 apply 时立即失败；schema_version 为将来兼容迁移留出把手。

### D5 运行时资源单一门面 + 三协作对象

`SharedResourceMount`（5 个 Mixin 组合）持有全部资源状态；启动/释放/访问器刷新分别由 `RuntimeResourceBootstrapper` / `RuntimeResourceReleaser` / `RuntimeAccessorRefresher` 编排。路由与用例永不直接创建外部连接。
**原因**：生命周期一处收敛才可能做原子热更新与有序停机；协作对象拆分避免上帝类同时保持状态单源。

### D6 配置热更新 = 候选构建 + 原子切换 + 延迟释放

`SettingsApplyTransaction` 承载 commit/rollback；`RuntimeBundle`（frozen + generation）是唯一一致性读取单元；hot_reload_allowed/restart_required 白名单声明在 `config/app_base.toml`。
**原因**：见[运行时资源生命周期](runtime_resource_lifecycle.md)第 5 节；失败必须能回到旧状态并留下 `config_security_rejected` 审计事件。

### D7 同步用例 + 有界线程池桥接（而非全面 async）

`RequestExecutionBridge`：容量 = workers+queue，双超时（排队 2s / 执行 15s），超限 503、超时 504，饱和度进指标。
**原因**：psycopg 同步池 + argon2 哈希本质阻塞；显式容量给出可推理的背压与拒绝行为，避免隐式 anyio 默认线程池（无界排队）。

### D8 生产安全强约束前置到启动期

`SettingsSecurityValidator` 在配置加载时校验生产环境：JWT 密钥必须外部注入且非弱值、连接串必须存在；启动器另拦生产 bootstrap admin 与生产内存缓存。
**原因**：安全配置错误的最佳失败点是部署时而不是被攻击时。

### D9 中间件顺序由计划对象统一生成

`FastApiMiddlewarePlan.build_bindings` 产出有序列表，装配器一次性前插 `app.user_middleware`；Prometheus HTTP 指标中间件是指标配置开启后的额外最外层。
**原因**：顺序即安全语义（作用域先于一切、载荷防护先于认证、认证先于限流），集中声明可被单测锁定。

### D10 任务可靠性：同事务 Outbox + 重扫补发

派发时执行记录与 Outbox 同事务落库；发布成功才标记 published；启动时与后台线程（5s 周期、60s 安全窗口）重扫 RESERVED 记录补发；本地任务后端禁止搭配 RabbitMQ 总线（防重复执行）。
**原因**：消除"记录已写、消息未发"或反之的双写不一致；at-least-once 语义配合任务侧 `deduplication_key` 唯一约束达到有效一次处理。

### D11 审计关键日志同步落库，普通日志缓冲批刷

`LogPersistencePriority.AUDIT_CRITICAL`（管理员身份变更、配置安全拒绝）绕过缓冲在发射线程内同步写库；标准事件走容量/时间窗口双触发的缓冲批量刷盘，失败可降级 stdout 并计数进指标与告警（`audit_critical_write_failure`）。
**原因**：审计完整性不允许"进程崩溃丢缓冲"；普通访问日志用吞吐换延迟。

### D12 授权真值以数据库为准，令牌只是快照

认证中间件每请求经仓储重建 `AuthorizationSnapshot` 并校验令牌会话状态（存在/主体一致/未吊销/未过期/一致性）；刷新令牌轮换强制开启（`refresh_token_rotation_enabled` 必须为 true），复用旧刷新令牌立即吊销整个会话族。
**原因**：权限变更/封号即时生效；刷新令牌重放攻击的爆炸半径被限制为单会话。

## 3. 如何新增决策

1. 写清背景、决策、原因、影响与代码锚点，追加到本清单。
2. 涉及代码约束的补测试保护（unit/contract/boundary 任一层）。
3. 大型决策复制 [ADR 模板](../templates/decision_record_template.md)建正式记录后从此处链接。

## 4. 测试覆盖

| 测试类型 | 文件 | 验证决策 |
| --- | --- | --- |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | D2 |
| unit | `test/unit_test/test_settings_security_unit.py` | D8 |
| unit | `test/unit_test/test_request_execution_bridge_unit.py` | D7 |
| contract | `test/contract_test/test_http_contract.py` | D3、D4 |
| path | `test/path_test/test_runtime_path.py` | D5、D6 |
| integration | `test/integration_test/test_funboost_rabbitmq_integration.py` | D10 |

## 5. 相关文档

- [项目文档总览](../README.md)
- [架构总览](architecture_overview.md)
- [运行时资源生命周期](runtime_resource_lifecycle.md)
- [ADR 模板](../templates/decision_record_template.md)
