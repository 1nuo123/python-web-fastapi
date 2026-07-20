# 应用端口

## 1. 文档目的
说明用例层如何通过端口访问设置、认证、任务、日志、身份、审计和配置热更新能力。

**最后更新范围**：覆盖 `src/application/ports` 下的 Protocol 和数据快照。

## 2. 适用读者
- 新人开发者
- 后端开发者
- 测试维护者

## 3. 关联源码
| 路径 | 作用 |
| --- | --- |
| `src/application/ports/auth_runtime_port.py` | 认证运行时端口。 |
| `src/application/ports/task_runtime_port.py` | 任务运行时端口。 |
| `src/application/ports/settings_reader_port.py` | 配置读取端口。 |
| `src/application/ports/admin_identity_port.py` | 管理员身份端口。 |
| `src/application/ports/admin_log_query_port.py` | 日志查询端口。 |
| `src/application/ports/admin_audit_query_port.py` | 审计查询端口。 |
| `src/application/ports/admin_settings_reload_port.py` | 配置热更新端口。 |
| `src/application/ports/application_port_contract.py` | 运行时端口契约信封。 |
| `src/application/ports/admin_regression_result.py` | 业务后台回归结果契约。 |

## 4. 核心结论
- 端口使应用层不依赖具体数据库、缓存或消息实现。
- `SharedResourceMount` 实现多个端口并持有真实资源。
- `AdminSettingsReloadPort` 由 `AdminSettingsReloadAdapter` 包装 `SettingsReloadCoordinator`，不是 `SharedResourceMount` 直接实现。
- `ApplicationPortEnvelope` 当前只覆盖 auth_runtime、settings_reader、task_runtime 三类运行时端口，不覆盖后台查询端口。
- 端口数据对象多以 Snapshot、Query、Result 命名。
- 应用层不得直接导入基础设施实现，边界由 `test_application_port_boundary_unit.py` 保护。

## 5. 结构说明
端口文件定义输入查询、输出快照和 Protocol；基础设施层多在资源门面中提供实现，少数能力用专门 adapter 接入运行时协调器。

## 6. 工作流程
```mermaid
flowchart LR
    Usecase["Application Usecase"] --> Port["Application Port Protocol"]
    Port --> Mount["SharedResourceMount"]
    Mount --> Infra["Repository/Runtime Adapter"]
```

## 7. 关键实现
| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `AuthRuntimePort` | `src/application/ports/auth_runtime_port.py` | 认证能力端口。 |
| `TaskRuntimePort` | `src/application/ports/task_runtime_port.py` | 任务能力端口。 |
| `AdminSettingsReloadPort` | `src/application/ports/admin_settings_reload_port.py` | 构建并应用配置热更新候选。 |
| `AdminIdentityPort` | `src/application/ports/admin_identity_port.py` | 管理员 scope/role/user/initial_admin 能力。 |
| `AdminAuditQueryPort` | `src/application/ports/admin_audit_query_port.py` | 业务审计分页查询。 |
| `SharedResourceMount` | `src/infrastructure/shared_resource_mount.py` | 端口实现门面。 |

## 8. 如何修改或扩展
1. 先判断是否已有端口可复用。
2. 新增端口时用 Protocol 描述最小能力。
3. 在 `SharedResourceMount` 或独立 adapter 中实现端口。
4. 补端口边界测试。

## 9. 测试覆盖
| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_application_port_boundary_unit.py` | 端口边界。 |
| unit | `test/unit_test/test_admin_settings_usecase_unit.py` | 配置热更新端口行为。 |
| unit | `test/unit_test/test_admin_log_query_unit.py` | 日志查询端口行为。 |
| unit | `test/unit_test/admin_audit/test_admin_audit_query_unit.py` | 审计查询端口行为。 |
| contract | `test/contract_test/admin_identity/test_admin_identity_business_boundary_contract.py` | 业务后台回归结果契约。 |

## 10. 常见问题
- 如果端口方法越来越大，考虑拆分为更小的 query/command 端口。

## 11. 维护备注
端口变更时同步用例文档、基础设施文档和测试说明。



## 12. 相关文档
- [项目文档总览](../README.md)
- [依赖方向](../01_architecture/dependency_direction.md)
