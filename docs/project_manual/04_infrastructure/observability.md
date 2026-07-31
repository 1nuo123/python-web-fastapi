# 可观测性

## 1. 这是什么

详解可观测性三件套：Prometheus 指标（注册器、指标族、`/metrics` 出口、基数控制）、OpenTelemetry 追踪桥接、告警规则基线（版本化 YAML + 契约校验）。回答"暴露了哪些指标、每个标签从哪来、告警阈值是什么、trace id 怎么流转"。

**最后更新范围**：覆盖 `src/core/observability_contract/`、`src/infrastructure/observability/` 3 个文件、`fastapi_otel_bridge.py`、`config/runtime/metrics_runtime/` 与 `config/observability/alert_rules.yml`。

## 2. 设计思想与动机

- **指标默认关闭、按族裁剪**：`metrics_runtime_base.toml` 中 `enabled=false`（test/production 覆盖亦保持关闭，按部署需要显式开启）。开启后还可用 6 个 `include_*` 开关裁剪指标族，最小暴露面原则。
- **标签基数是硬约束**：HTTP path 标签用路由模板而非原始路径；注册器再做动态段防御（纯数字/长十六进制段 → `unknown`）；安全事件、任务、刷盘原因标签全部取自封闭枚举。任何新增标签必须论证基数上界。
- **应用不承载告警执行**：告警规则以 `AlertRuleCatalogEnvelope` 契约版本化在仓库（`config/observability/alert_rules.yml`），由外部 Prometheus 挂载引用；`AlertRuleCatalogLoader` 提供契约校验（测试确保规则文件永远合法且引用的指标名存在）。
- **拉模式 + 抓取时刷新**：`/metrics` 被抓取时刷新 ready 指标与运行时饱和度（事件式而非常驻采样线程），实现零后台开销。

## 3. 指标目录

| 指标 | 类型 | 标签 | 语义与来源 |
| --- | --- | --- | --- |
| `fastapi_request_total` | Counter | method, path, status_code | HTTP 请求数（PrometheusHttpMetricsMiddleware，path=路由模板） |
| `fastapi_request_duration_seconds` | Histogram | 同上 | 请求耗时（最外层中间件计时） |
| `fastapi_runtime_ready` | Gauge | — | app.state.ready（抓取时刷新） |
| `fastapi_security_event_total` | Counter | event_type, decision, severity | 每条安全事件（枚举白名单标签） |
| `fastapi_log_buffer_flush_total` | Counter | reason, failed | 日志刷盘按批事件数累加（reason ∈ LogWriteReason：buffer_limit/interval/shutdown/manual/audit_critical） |
| `fastapi_log_buffer_pending_items` | Gauge | — | 缓冲+队列待落库事件数 |
| `fastapi_task_execution_total` | Counter | task_name, outcome | 任务结果（outcome ∈ success/failed/rejected；task_name=job_kind 低基数集合） |
| `fastapi_runtime_saturation_ratio` | Gauge | resource | 有界资源饱和度 0-1（resource ∈ request_thread_pool/db_pool/task_queue/log_buffer），启动/热更新/抓取三时点刷新，超界值收敛 |

## 4. 装配与配置

`FastApiAppAssembler._bind_prometheus_metrics`：`runtime.metrics.header.enabled=true` 时构建 `PrometheusMetricsRegistry(options=4 个 include 开关)` → `resource_mount.install_metrics_registry`（日志缓冲、任务存储、饱和度刷新由此取到注册器）→ `include_http_metrics` 决定是否加 HTTP 指标中间件 → `PrometheusMetricsRoute.bind`（`metrics_path` 默认 `/metrics`，`include_in_schema=False` 不进 OpenAPI，无鉴权——生产依赖网络层控制抓取来源）。

配置信封（`runtime.metrics`）：`header{mode=prometheus_metrics, enabled, policy_name}` + `detail{metrics_path, include_http_metrics, include_runtime_metrics, include_security_metrics, include_task_metrics, include_log_buffer_metrics, include_saturation_metrics}`。指标配置属 restart_required。

## 5. 告警规则基线（alert_rules.yml）

6 条规则（threshold_alert / absence_alert 两种 kind，契约校验规则名唯一与版本一致）：

| 规则 | 级别 | 表达式要点 | 等待 |
| --- | --- | --- | --- |
| `http_5xx_error_rate_high` | critical | 5xx 占比 > 5%（5m rate） | 300s |
| `http_p95_latency_high` | warning | P95 > 1s（histogram_quantile） | 300s |
| `runtime_ready_down` | critical | `absent(fastapi_runtime_ready) or == 0` | 120s |
| `log_buffer_flush_failure_growing` | warning | failed=true 10m 增量 > 0 | 0 |
| `audit_critical_write_failure` | critical | reason=audit_critical,failed=true 5m 增量 > 0 | 0 |
| `task_execution_failure_rate_high` | warning | failed 占比 > 20%（10m rate） | 600s |

## 6. OpenTelemetry 桥接

`FastApiOtelBridge`（配置 `runtime.otel`：enabled、service_name、exporter_endpoint、traces_sample_ratio 0-1）：

- `enabled=false`（默认）：完全 no-op，不做 instrument；trace id 从请求头 `X-Trace-ID` 透传（信任上游生成）。
- `enabled=true`：`FastAPIInstrumentor.instrument_app`；trace id 优先解析 W3C `traceparent` 第二段，缺失回落 `X-Trace-ID`。
- 无论开关，trace id 都进入 `RequestScope` → 响应头/统一信封/结构化日志，保证"没有 OTel 后端也能靠 header 串链路"。

## 7. 怎么用

- 开启指标：目标环境 `metrics_runtime_{env}.toml` 置 `header.enabled=true`，重启；Prometheus 抓 `<host>:8000/metrics`。
- 接 Grafana/告警：参照 [observability Grafana Prometheus 接入说明](../../observability_grafana_prometheus接入说明.md)；规则文件直接挂载给 Prometheus ruler。
- 新增指标：注册器加指标字段与 record 方法（标签枚举化）→ 产生点调用 → 按需加 include 开关 → 补 unit + interface 测试 → 评估是否加告警规则。

## 8. 注意事项

- `/metrics` 无认证鉴权，生产开启时必须限制抓取网络来源（安全组/网络策略），不要暴露公网。
- Histogram 用默认桶；若 SLO 需要更细的低延迟分辨率需自定义 buckets（当前未配）。
- 每个 worker 进程一套注册器：多副本部署时 Prometheus 按 instance 聚合，不要在单实例视角解读 Counter。
- 修改指标名/标签等于破坏外部契约（面板与告警同时失效），按告警基线与面板闭环流程走变更。

## 9. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_prometheus_metrics_registry_unit.py` | 指标族、开关裁剪、路径归一化。 |
| unit | `test/unit_test/test_fastapi_otel_bridge_unit.py` | trace id 解析与 no-op。 |
| unit | `test/unit_test/test_alert_rule_catalog_unit.py` | 规则文件契约校验。 |
| interface | `test/interface_test/test_metrics_http_interface.py` | `/metrics` 输出与路由模板标签。 |
| initialization | `test/initialization_test/test_observability_initialization.py` | 指标装配与饱和度刷新。 |

## 10. 相关文档

- [项目文档总览](../README.md)
- [日志运行时](logging_runtime.md)
- [observability Grafana Prometheus 接入说明](../../observability_grafana_prometheus接入说明.md)
- [运维检查清单](../07_configuration_deployment/operations_checklist.md)
