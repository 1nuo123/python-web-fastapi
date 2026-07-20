# Web模块注册收口分步骤执行方案

## 1. 阶段目标
降低新增 Web 模块时对核心枚举和硬编码导入清单的改动。

阶段完成后：新增模块通过集中 manifest/registry 登记，路由装配自动从 registry 构建 bundle。

本阶段按硬迁移口径执行：一次性将当前硬编码 provider 导入与模块启用边界迁移到集中注册模型，不保留旧 catalog 硬编码路径。

## 2. 依赖关系
| 依赖项 | 说明 |
|---|---|
| Phase 3 | 依赖配置模型拆分结果，模块启用配置需支持集中读取和校验。 |
| Phase 4 | 依赖应用层边界隔离结果，新增 provider 不应迫使应用层反向依赖基础设施实现。 |
| `WebBundleCatalog` | 当前存在显式 provider 导入与组装逻辑，需迁移到 manifest 驱动。 |
| `ApplicationModuleName` | 当前新增模块仍可能需要改核心枚举，需收口模块名边界。 |
| `web_bundle_contract.py` | 当前 Web bundle 契约需补充与 manifest 的一致性校验。 |
| 模块启用配置 | 需保持已有模块启用/禁用行为。 |

## 3. 模拟用法
原始模拟用法保留如下，用于表达新增模块只改集中 manifest 的目标：

```python
WEB_MODULE_MANIFEST = [
    WebModuleManifestEntry(module_name="health_probe", provider_path="...HealthProbeBundleProvider"),
    WebModuleManifestEntry(module_name="auth_access", provider_path="...AuthAccessBundleProvider"),
]
```

硬迁移落地时，最终契约应使用公共头字段和强类型扩展字段承载上述语义。

## 4. 契约
本阶段契约采用“公共头字段 + 强类型扩展字段”规则：

- 外层信封使用公共头字段。
- 扩展字段使用 Pydantic 判别联合。
- 扩展字段必须包含 `kind`、`schema_version`。
- 扩展模型必须启用 `extra="forbid"`。
- 禁止使用 `dict[str, Any]`、`metadata`、`extra_payload` 承载扩展内容。
- 外层类型与内层扩展类型的 `kind`、`schema_version` 必须一致。

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| `WebModuleHeader` | Web 模块公共头 | 承载 `kind`、`schema_version`、`module_name`、`enabled`。 |
| `RouterProviderDetail` | 路由提供者扩展 | `kind="router_provider"`，声明 provider 导入路径和路由标签。 |
| `WebModuleManifestEnvelope` | Web 模块清单信封 | 外层公共头 + 判别联合扩展；扩展含 `kind`、`schema_version`，`extra="forbid"`。 |
| `WebBundleProviderEnvelope` | Web Bundle 提供者信封 | 保留现有 provider 信封语义，补充与 manifest 的一致性校验。 |

## 5. 分步骤执行方案
### Step 1：新增集中 manifest 契约和内置模块清单
新增 `src/api/web_module_manifest.py`，集中声明内置 Web 模块 provider。

执行要求：
- 使用 `WebModuleHeader` + `RouterProviderDetail` 表达模块名、启用状态、provider 导入路径和标签。
- 使用 Pydantic 判别联合表达扩展字段。
- 扩展字段包含 `kind`、`schema_version`。
- 扩展模型启用 `extra="forbid"`。
- 不使用 `dict[str, Any]`、`metadata`、`extra_payload` 承载稳定协议字段。

验收点：
- 当前健康、鉴权、系统信息模块均出现在集中 manifest。
- 新增模块入口集中在 manifest/registry。

### Step 2：替换 `WebBundleCatalog` 硬编码导入
修改 `WebBundleCatalog`，由 manifest 动态导入 provider 并构建 bundle。

执行要求：
- 删除 catalog 内显式 provider import 清单。
- 通过 provider 导入路径加载 provider 类型。
- 校验 provider 实例满足现有 Web bundle 契约。
- 导入失败时给出明确配置错误，不吞掉异常。
- 不保留旧硬编码 provider 注册路径。

验收点：
- 当前 `/health/*`、`/auth/*`、`/system/info` 路由仍正常装配。
- 新增 provider 时只改 manifest 即可被 catalog 发现。

### Step 3：调整模块名边界
调整 `ApplicationModuleName` 使用边界，使配置启用项允许字符串模块名。

执行要求：
- 内置常量可保留用于避免拼写错误。
- 配置启用项不再强制只能来自核心枚举。
- manifest 中的 `module_name` 是模块发现和启用控制的唯一业务键。
- 旧枚举不得成为新增模块的必改入口。

验收点：
- 新增一个示例 Web 模块不需要修改核心模块枚举。
- 已有模块名保持兼容。

### Step 4：增加 manifest 与 provider 一致性校验
在 catalog 构建阶段校验 manifest 与 provider 输出。

执行要求：
- 校验 `module_name` 一致。
- 校验重复模块名。
- 校验 provider 缺失或导入失败。
- 校验禁用模块不会 include router。
- 校验 provider 路由标签和模块配置可被读取。

验收点：
- 重复模块名失败。
- provider 缺失失败。
- 禁用模块不挂载路由。
- provider 与 manifest 模块名不一致失败。

### Step 5：保持现有路由行为
迁移后保持当前路由和响应行为不变。

执行要求：
- 保持 `/health/*` 路由路径不变。
- 保持 `/auth/*` 路由路径不变。
- 保持 `/system/info` 路由路径不变。
- 保持当前测试工厂可创建 app。
- 不改变现有接口响应结构。

验收点：
- 健康、鉴权、系统信息路径回归通过。
- `TestAppFactory().create()` 能正常装配全部路由。

## 6. 关键代码片段
原始关键代码片段保留如下：

```python
class WebModuleManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    header: WebModuleHeader
    detail: RouterProviderDetail
```

## 7. 校验与验收点
- 新增一个测试 provider 后，只修改 manifest 即可被 catalog 发现。
- 禁用模块不会 include router。
- 现有三组路由路径保持不变。
- manifest 与 provider 的 `module_name` 不一致时明确失败。
- 重复模块名、缺失 provider、导入失败均有测试覆盖。
