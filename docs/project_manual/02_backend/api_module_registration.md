# API 模块注册

## 1. 这是什么

说明 Web API 模块（`src/api/endpoint_*`）如何通过"manifest 清单 → provider 装载 → composer 挂载"三段机制注册进应用，以及每一段做了哪些一致性校验。新增/启停一个 API 模块的全部机制都在这里。

**最后更新范围**：覆盖 `web_module_manifest.py`、`web_bundle_catalog.py`、`fastapi_route_composer.py` 与 `app.modules.enabled` 配置联动。

## 2. 设计思想与动机

FastAPI 原生的 `include_router` 若散落各处，会出现：路由重复注册难发现、模块无法按环境启停、后台模块权限策略无人核对。本项目将其收敛为**声明式清单 + 动态装载 + 配置启用**：

- **manifest 是唯一模块名录**：`WebModuleManifestRegistry.list_entries()` 内置 9 个 `WebModuleManifestEnvelope`，每条声明 `module_name`、`provider_import_path`（字符串形式的类路径，避免装配期 import 全部模块）、`route_tags`、`admin_boundary_policy`（public / business_admin / ops_only）。
- **provider 是模块自描述**：每个 endpoint 包内的 `*BundleProvider`（继承 `WebBundleProvider`）返回 `WebBundleProviderEnvelope{header{module_name}, detail{provider_name}, bundle{module_name, router}}`。路由的真实构建在 `*RouteCatalog.__init__` 内完成（`APIRouter(tags=[...])` + 若干 `add_api_route`）。
- **配置决定启用**：`app.modules.enabled`（TOML 列表）决定哪些模块真正挂载。运维控制面模块（admin_task/admin_settings/admin_log/security_protection/system_overview）默认不启用，需显式加入。

## 3. 三段机制与校验点

```mermaid
flowchart LR
    M["WebModuleManifestRegistry<br/>9 条清单"] -->|list_entries| C["WebBundleCatalog"]
    C -->|importlib 动态装载| P["*BundleProvider.provide()"]
    P -->|WebBundle| R["FastApiRouteComposer.compose"]
    S["settings.app.modules.enabled"] --> R
    R -->|include_router(prefix=api_prefix)| APP["FastAPI app"]
    R -->|mounted_modules| RM["resource_mount.set_enabled_web_modules"]
```

校验点（全部在启动期触发，失败即启动失败）：

| 阶段 | 校验 | 失败信息 |
| --- | --- | --- |
| Catalog 构造 | manifest 模块名不重复；provider import 路径非空；route_tags 非空 | `DUPLICATE_MODULE_MESSAGE` 等 |
| Catalog 构造 | 后台边界策略与领域授权事实源交叉校验：`business_admin` 集合必须 == {admin_identity, admin_audit}，`ops_only` 集合必须 == {admin_task, admin_settings, admin_log, security_protection, system_overview}，且两组集中授权要求非空 | `ADMIN_BOUNDARY_POLICY_MISMATCH_MESSAGE` |
| 装配步骤 2 | `validate_enabled_modules`：配置启用的模块必须存在于 manifest 启用集 | 列出未知模块与全部可用模块名 |
| provider 装载 | import 成功、类型必须继承 `WebBundleProvider`、provider 输出 module_name 与 manifest 一致、`router.tags` 与 manifest `route_tags` 一致、禁用模块不得被装配 | `PROVIDER_*_MESSAGE` |
| composer | 启用模块必须全部挂载成功（反向核对） | `启用的 Web 模块未完成路由挂载: ...` |

## 4. 当前模块清单

| module_name | provider | 边界策略 | 默认启用 |
| --- | --- | --- | --- |
| `health_probe` | `HealthProbeBundleProvider` | public | 是 |
| `auth_access` | `AuthAccessBundleProvider` | public | 是 |
| `admin_identity` | `AdminIdentityBundleProvider` | business_admin | 是 |
| `admin_audit` | `AdminAuditBundleProvider` | business_admin | 是 |
| `system_overview` | `SystemOverviewBundleProvider` | ops_only | 否 |
| `security_protection` | `SecurityProtectionBundleProvider` | ops_only | 否 |
| `admin_task` | `AdminTaskBundleProvider` | ops_only | 否 |
| `admin_settings` | `AdminSettingsBundleProvider` | ops_only | 否 |
| `admin_log` | `AdminLogBundleProvider` | ops_only | 否 |

（默认启用来自 `config/app_base.toml` 的 `app.modules.enabled`；各环境可覆盖。）

## 5. 怎么用：新增一个模块的最小步骤

1. `src/core/http_contract/web_bundle_contract.py` 的 `ApplicationModuleName` 加枚举值。
2. 新建 `src/api/endpoint_<name>/`：`contract_<name>.py`（请求/响应模型）+ `route_<name>.py`（`<Name>RouteCatalog` + `<Name>BundleProvider`）。
3. `web_module_manifest.py`：加 provider import 路径常量、route tag 常量，`list_entries()` 追加信封；若是后台模块，还要加入 `BUSINESS_ADMIN_MODULE_NAMES` 或 `OPS_ONLY_MODULE_NAMES` 并在 `src/domain/auth/admin_route_authorization_policy.py` 声明对应 requirement（否则启动即报边界策略不一致）。
4. 配置：目标环境的 `app.modules.enabled` 加模块名。
5. 测试：manifest unit 测试更新计数/集合断言；补 interface 测试。

完整流程见[新增 API](../09_development_guide/adding_new_api.md)。

## 6. 注意事项

- provider 用**字符串 import 路径**装载是有意设计：manifest 文件不 import 具体路由模块，避免"清单文件成为全项目 import 汇聚点"引发循环依赖；代价是拼错路径要到启动才发现（有校验兜底）。
- `RouteCatalog` 在 provider 每次 `provide()` 时新建，`APIRouter` 与路由函数因此每应用实例独立——测试并行构建多个 app 不会互相污染。
- 一个模块 = 一个 `APIRouter` = 一组 tags；不要在一个 catalog 里混多个 tag，OpenAPI 分组与 manifest 校验都按单 tag 约定。
- `api_prefix`（`runtime.web.api_prefix`）由 composer 统一加在 include_router 上；模块内路径常量不含前缀，文档中的路径均为模块自身路径。

## 7. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | 清单内容、边界策略交叉校验。 |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | manifest、provider 装载与启用模块校验。 |
| interface | `test/interface_test/test_http_interface.py` | 启用模块的路由可达性。 |
| integration | `test/integration_test/test_app_integration.py` | 未知启用模块失败、前缀路由/OpenAPI 与真实配置装配。 |

## 8. 相关文档

- [项目文档总览](../README.md)
- [FastAPI 应用装配](fastapi_app_assembly.md)
- [路由契约模式](route_contract_pattern.md)
- [新增 API](../09_development_guide/adding_new_api.md)
