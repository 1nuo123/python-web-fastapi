# 术语表

## 1. 文档目的
统一解释项目中的高频概念，减少跨文档命名漂移。

**最后更新范围**：覆盖当前代码中的 WebBundle、RouteCatalog、ResponseEnvelope、SharedResourceMount、runtime、scope 等术语。

## 2. 适用读者
- 新人开发者
- 后端开发者
- 测试维护者
- 运维部署人员
- 安全审查人员

## 3. 关联源码
| 路径 | 作用 |
| --- | --- |
| `src/core/http_contract/web_bundle_contract.py` | WebBundle 和 ApplicationModuleName。 |
| `src/core/http_contract/response_envelope_contract.py` | ResponseEnvelope。 |
| `src/infrastructure/shared_resource_mount.py` | SharedResourceMount。 |
| `src/domain/auth/auth_scope_code.py` | AuthScopeCode。 |
| `src/domain/auth/auth_role_key.py` | AuthRoleKey。 |

## 4. 核心结论
- WebBundle 是路由模块装配单元。
- RouteCatalog 是每个 endpoint 模块内部注册 FastAPI 路由的类。
- ApplicationModuleName 是 Web 模块名枚举，当前包括 `health_probe`、`auth_access`、`system_overview`、`security_protection`、`admin_task`、`admin_settings`、`admin_log`、`admin_identity`、`admin_audit`。
- ResponseEnvelope 是统一 HTTP 响应结构。
- SharedResourceMount 是运行时资源和应用端口的门面。
- runtime 指 `config/runtime/*_runtime` 合并后的运行时配置树，当前覆盖 web、auth、database、cache、message、task、otel、metrics、logging、security、distributed_lock、key_management。
- scope 当前包括 `auth:read`、`auth:manage`、`security:manage`、`system:read`、`task:dispatch`。

## 5. 结构说明
术语来自源码中的类名、枚举和配置键；如果术语未能从代码确认，则保留为“待确认”。

## 6. 工作流程
非流程类文档：本文件作为统一词汇索引，其他文档链接回此处。

## 7. 关键实现
| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `ResponseEnvelope` | `src/core/http_contract/response_envelope_contract.py` | 统一响应信封。 |
| `SharedResourceMount` | `src/infrastructure/shared_resource_mount.py` | 运行时资源门面。 |
| `AuthScopeCode` | `src/domain/auth/auth_scope_code.py` | 授权 scope 枚举。 |

## 8. 如何修改或扩展
1. 新增重要概念时先加入本术语表，再在专题文档使用一致名称。

## 9. 测试覆盖
| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_fastapi_app_assembler_unit.py` | 验证 FastAPI 装配器行为。 |
| contract | `test/contract_test/test_http_contract.py` | 验证 HTTP 契约模型。 |
| interface | `test/interface_test/test_http_interface.py` | 验证 HTTP 接口表面。 |

## 10. 常见问题
- 待确认：如果未来加入前端或网关层，其术语需由对应代码确认后补入。

## 11. 维护备注
修改术语时同步搜索 `docs/project_manual` 中同名概念，保持用语一致。



## 12. 相关文档
- [项目文档总览](../README.md)
- [架构总览](../01_architecture/architecture_overview.md)
