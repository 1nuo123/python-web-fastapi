# Web模块注册收口分步骤任务清单

## Step 1：新增集中 manifest 契约和内置模块清单
- [x] 新增 `src/api/web_module_manifest.py`。
- [x] 定义 `WebModuleHeader`。
- [x] 定义 `RouterProviderDetail`。
- [x] 定义 `WebModuleManifestEnvelope`。
- [x] 使用 Pydantic 判别联合承载 provider 扩展。
- [x] 扩展字段包含 `kind`、`schema_version`。
- [x] 扩展模型启用 `extra="forbid"`。
- [x] 禁止使用 `dict[str, Any]`、`metadata`、`extra_payload` 承载稳定协议字段。
- [x] 将健康模块登记到 manifest。
- [x] 将鉴权模块登记到 manifest。
- [x] 将系统信息模块登记到 manifest。

## Step 2：替换 `WebBundleCatalog` 硬编码导入
- [x] 删除 catalog 内显式 provider import 清单。
- [x] 通过 manifest 的 provider 导入路径加载 provider 类型。
- [x] 校验 provider 实例满足现有 Web bundle 契约。
- [x] provider 导入失败时抛出明确配置错误。
- [x] 删除旧硬编码 provider 注册路径。
- [x] 保持 catalog 对外构建 bundle 的入口稳定。

## Step 3：调整模块名边界
- [x] 保留内置模块常量用于避免拼写错误。
- [x] 配置启用项允许字符串模块名。
- [x] 将 manifest 中的 `module_name` 作为模块发现业务键。
- [x] 将 manifest 中的 `module_name` 作为启用控制业务键。
- [x] 确认新增模块不需要修改核心模块枚举。

## Step 4：增加 manifest 与 provider 一致性校验
- [x] 校验 manifest 与 provider 的 `module_name` 一致。
- [x] 校验重复模块名。
- [x] 校验 provider 缺失。
- [x] 校验 provider 导入失败。
- [x] 校验禁用模块不会 include router。
- [x] 校验 provider 路由标签可被读取。
- [x] 校验 provider 模块配置可被读取。

## Step 5：保持现有路由行为
- [x] 保持 `/health/*` 路由路径不变。
- [x] 保持 `/auth/*` 路由路径不变。
- [x] 保持 `/system/info` 路由路径不变。
- [x] 保持当前测试工厂可创建 app。
- [x] 保持现有接口响应结构不变。

## Step 6：阶段校验
- [x] 新增一个测试 provider 后，只修改 manifest 即可被 catalog 发现。
- [x] 禁用模块不会 include router。
- [x] 重复模块名会失败。
- [x] 缺失 provider 会失败。
- [x] provider 导入失败会失败。
- [x] provider 与 manifest 模块名不一致会失败。
- [x] 健康、鉴权、系统信息路径回归通过。
