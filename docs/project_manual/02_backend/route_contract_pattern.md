# 路由契约模式

## 1. 这是什么

说明每个 API 模块内部 `contract_*.py` + `route_*.py` 的固定写法（RouteCatalog 模式），包括路由函数的标准骨架、守卫依赖声明方式、分页信封与"header+detail"响应契约的用法。写任何新接口前先读本文。

**最后更新范围**：覆盖 9 个 endpoint 模块的共同模式、`admin_list_page_contract.py` 分页契约与 `HealthProbeRouteCatalog` 完整示例。

## 2. 设计思想与动机

- **contract 与 route 分离**：`contract_*.py` 只放 Pydantic 模型（请求体、响应 payload、查询信封），`route_*.py` 只放 HTTP 适配。模型可被 contract 测试独立校验，路由文件保持"读依赖 → 调用例 → 包信封"三步节奏。
- **类持有 router 而非模块级装饰器**：`*RouteCatalog.__init__` 里显式 `add_api_route`，而不是 `@router.get(...)` 装饰器。动机：路由注册顺序、response_model、dependencies 全部集中可见；catalog 可被多次实例化（每个 app 独立）；守卫方法可以是实例方法（共享 `self._accessor`）。
- **响应模型进 OpenAPI**：每条 `add_api_route` 都声明 `response_model=ResponseEnvelope[XxxPayload]`，OpenAPI 文档与运行时序列化同源。
- **请求模型一律 `extra="forbid"` + 字段约束**：未知字段、越界值在进入用例前就被 422 拦截，用例只处理已验证输入。

## 3. 标准骨架

以健康探针为例（最简完整形态）：

```35:61:src/api/endpoint_health_probe/route_health_probe.py
class HealthProbeRouteCatalog:
    """
    健康探针路由目录，负责注册接口与响应契约。
    """

    def __init__(self) -> None:
        ...
        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[HEALTH_ROUTE_TAG])
        self.router.add_api_route(
            HEALTH_LIVE_PATH,
            self.get_live,
            methods=["GET"],
            response_model=ResponseEnvelope[HealthProbePayload],
        )
```

路由函数固定三步：

```python
async def get_live(self, request: Request) -> ResponseEnvelope[HealthProbePayload]:
    # 1. 经桥接器执行同步用例（execution_name 与运行时配置匹配）
    result = await self._accessor.read_request_execution_bridge(request).run_sync(
        execution_name=HEALTH_REQUEST_EXECUTION_NAME,
        callable_object=self._accessor.read_health_probe_usecase(request).execute,
        probe_kind=HEALTH_LIVE_PROBE_KIND,
    )
    # 2. 用例结果 → 接口 payload（contract 提供 from_result 类方法）
    payload = HealthProbePayload.from_result(result)
    # 3. 统一信封包装
    return self._accessor.read_response_factory(request).build(
        code=str(SuccessCode.OK),
        message="健康探针正常。",
        request_scope=self._accessor.read_request_scope(request),
        data=payload,
    )
```

需要授权的路由在注册处声明守卫依赖（以 admin_settings 为例）：

```73:79:src/api/endpoint_admin_settings/route_admin_settings.py
        self.router.add_api_route(
            ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
            self.read_reload_candidate,
            methods=[ADMIN_SETTINGS_METHOD_GET],
            response_model=ResponseEnvelope[AdminSettingsReloadCandidateEnvelope],
            dependencies=[Depends(self.require_settings_reload)],
        )
```

守卫方法内部统一调用 `self._accessor.read_authorized_principal(request, <REQUIREMENT>)`，REQUIREMENT 来自 `src/domain/auth/admin_route_authorization_policy.py` 的集中常量，路由文件不自定义角色/scope 组合。

## 4. 契约模型的三种形态

| 形态 | 用途 | 例子 |
| --- | --- | --- |
| 请求模型 | body/query 校验，`extra="forbid"` + Field 约束 + 必要时 `model_validator` 规范化 | `TokenIssueRequest`（username 裁剪空白、1-128；password 1-256） |
| 响应 payload | `kind` + `schema_version` + 业务字段；常配 `from_result/from_snapshot` 类方法做用例结果→payload 映射 | `HealthProbePayload{kind="health_probe", schema_version="1.0", status, ready}` |
| header+detail 信封 | 列表/复合响应；header 声明操作与 kind，detail 为判别联合 | `AdminListPageEnvelope`、`AdminIdentityEnvelope`、`AdminTaskExecutionListEnvelope` |

分页统一复用 `src/api/admin_list_page_contract.py`：查询侧 `AdminListPageQuery{page_size(1..最大值，默认值与上限来自 admin_identity_port 常量), offset(>=0)}`，响应侧 `AdminListPagePayload{page_size, items, offset, total, next_cursor}`。新列表接口不要自造分页字段。

## 5. 怎么用：新接口检查单

1. contract：请求模型（约束写全）、响应 payload（kind/schema_version/映射方法）。
2. route catalog：路径/方法常量 → `add_api_route`（response_model + 守卫 dependencies）→ 路由函数三步骨架。
3. 授权：领域层选/加 requirement；守卫方法一行断言。
4. 用例调用一律经 `run_sync`（除非目标真是原生 async 函数且运行时配置了 native_async 策略）。
5. 错误：业务失败抛 `HttpFaultException(status_code, error_code, message)`，错误码用既有目录（`CoreErrorCode`/`AuthErrorCode`/`AdminIdentityErrorCode`），不发明裸字符串。
6. 测试：contract 测试锁字段约束，interface 测试锁 HTTP 行为（含 401/403/422 路径）。

## 6. 注意事项

- 路由函数不做业务分支：条件逻辑（如 ready 探针 503 转换）允许存在，但仅限"用例结果 → HTTP 语义"的映射；数据校验/组合查询/事务都下沉用例。
- `from_result` 映射方法放 contract 而不是 route，保证 payload 与用例结果的对应关系被 contract 测试覆盖。
- 每个模块的 METHOD 常量（如 `ADMIN_TASK_METHOD_GET = "GET"`）看似冗余，实际是全项目"禁止魔法字符串"规范的一部分；沿用即可。
- 修改响应 payload 字段 = 修改对外契约：需要同步 `public_contract_snapshot_builder` 基线、相关 API 文档与 interface 断言。

## 7. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| contract | `test/contract_test/test_http_contract.py` 等 | 请求/响应模型约束与信封一致性。 |
| interface | `test/interface_test/test_admin_task_interface.py` 等 | 路由行为、守卫、错误码。 |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | provider 输出、module/tag 一致性与 manifest 装载。 |
| path | `test/path_test/test_web_execution_path.py` | 装配后 Web 路由执行路径。 |

## 8. 相关文档

- [项目文档总览](../README.md)
- [API 模块注册](api_module_registration.md)
- [响应信封](response_envelope.md)
- [新增 API](../09_development_guide/adding_new_api.md)
