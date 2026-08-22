# Grafana 与 Prometheus 接入说明

> 修订时间：2026-08-19。本次修订与 `src/infrastructure/observability/prometheus_metrics_registry.py`、`config/observability/alert_rules.yml` 最终实现对齐；文档与源码冲突时以源码为准。

## 当前边界

应用侧指标与告警规则仍是代码事实源；开发环境另提供 `deploy/observability/compose.development.yml` 的本地 Prometheus、Grafana 和 Alertmanager 栈。该栈只绑定 loopback 端口、使用独立卷，不能作为生产部署配置。

- OpenTelemetry：配置与 FastAPI instrument 桥接已保留，默认关闭。
- Prometheus：通过 `runtime.metrics.header.enabled` 控制是否暴露 `/metrics`。
- Grafana：不直接接入应用代码，通过 Prometheus 数据源展示应用指标。
- 告警：应用不承载告警执行；告警规则基线随代码版本化在 `config/observability/alert_rules.yml`，由外部 Prometheus 挂载引用。

## 应用配置

指标运行时契约版本为 `1.1`（`metrics_runtime_contract.py`），除 HTTP 与 ready 开关外提供五个可独立关闭的指标族开关：

```toml
[runtime.header]
enabled = true

[runtime.detail]
metrics_path = "/metrics"
include_http_metrics = true
include_runtime_metrics = true
include_security_metrics = true
include_task_metrics = true
include_log_buffer_metrics = true
include_saturation_metrics = true
include_codex_diagnostic_metrics = true
```

`/metrics` 使用 Prometheus 文本格式返回，不使用项目统一 JSON 响应信封。开关关闭的指标族不注册、不出现在输出中。

## 指标清单

| 指标名 | 类型 | 标签 | 语义 |
|---|---|---|---|
| `fastapi_request_total` | Counter | `method`、`path`、`status_code` | HTTP 请求总数 |
| `fastapi_request_duration_seconds` | Histogram | `method`、`path`、`status_code` | HTTP 请求耗时 |
| `fastapi_runtime_ready` | Gauge | 无 | 应用 ready 状态 |
| `fastapi_security_event_total` | Counter | `event_type`、`decision`、`severity` | 安全事件总数，标签取值限定在 `SecurityEventType`/`SecurityEventDecision`/`SecurityEventSeverity` 封闭枚举 |
| `fastapi_log_buffer_flush_total` | Counter | `reason`（buffer_limit/interval/manual/shutdown/audit_critical）、`failed`（true/false） | 日志缓冲刷盘事件总数，按批次事件数量累加 |
| `fastapi_log_buffer_pending_items` | Gauge | 无 | 日志缓冲待落库事件数量（缓冲区 + 后台队列） |
| `fastapi_task_execution_total` | Counter | `task_name`（任务注册名）、`outcome`（success/failed/rejected） | 任务执行结果总数；`rejected` 表示去重拒绝复用既有记录 |
| `fastapi_runtime_saturation_ratio` | Gauge | `resource`（request_thread_pool/db_pool/task_queue/log_buffer） | 运行时有界资源饱和度（0-1），按容量策略上限折算 |
| `fastapi_codex_client_diagnostic_total` | Counter | `source`、`error_code`、`outcome`（recorded/rate_limited） | Codex 客户端错误诊断处理数量；全部标签由服务端二次脱敏和白名单收敛，未记录主体、路径、异常正文或认证数据 |
| `fastapi_codex_client_performance_sample_total` | Counter | `metric`、`observation` | Codex 客户端性能样本数量；标签均为服务端封闭枚举，不包含用户、会话、路由或自由文本 |
| `fastapi_codex_client_performance_value` | Gauge | `metric`、`observation` | 最近一条受限性能样本的数值；单位由 `metric` 固定，数值绝不成为标签 |

饱和度指标采用事件式刷新：应用启动完成、配置热更新提交与每次 `/metrics` 抓取时各刷新一次。

## Prometheus 抓取与告警规则引用示例

```yaml
scrape_configs:
  - job_name: fastapi-web-skeleton
    metrics_path: /metrics
    static_configs:
      - targets: ["app:8000"]
```

开发栈默认抓取当前隔离开发 app 的 `host.docker.internal:18005/metrics`；若 app 端口不同，应同步修改 `deploy/observability/prometheus/prometheus.yml`。启动命令和 smoke alert 恢复流程见 `deploy/observability/README.md`。生产仍需由运维将目标地址替换为实际服务名和端口。

告警规则基线文件为 `config/observability/alert_rules.yml`，结构由 `src/core/observability_contract/alert_rule_contract.py` 判别联合契约约束，并由契约测试保证可解析、字段合法。该文件是随代码版本化的规则事实源：部署监控栈时由运维将其中七条规则的 `promql_expression`、`for_duration_seconds` 与 `severity` 转写为外部 Prometheus 的 rule group 并挂载；应用自身不评估告警。七条基线规则：

| 规则名 | 级别 | 语义 |
|---|---|---|
| `http_5xx_error_rate_high` | critical | 5xx 错误率超过 5% 持续 5 分钟 |
| `http_p95_latency_high` | warning | P95 延迟超过 1 秒持续 5 分钟 |
| `runtime_ready_down` | critical | `fastapi_runtime_ready` 掉线或抓取缺失持续 2 分钟 |
| `log_buffer_flush_failure_growing` | warning | `fastapi_log_buffer_flush_total{failed="true"}` 在 10 分钟窗口内增长 |
| `audit_critical_write_failure` | critical | `fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}` 出现增长 |
| `task_execution_failure_rate_high` | warning | `fastapi_task_execution_total{outcome="failed"}` 失败率超过 20% 持续 10 分钟 |
| `codex_client_error_rate_high` | warning | `fastapi_codex_client_diagnostic_total{outcome="recorded"}` 速率超过每秒 10 条持续 5 分钟 |

## Grafana 数据源示例

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Grafana 面板读取 Prometheus，不直接访问应用数据库、日志表或业务接口。

## 面板建议

- QPS：`sum(rate(fastapi_request_total[5m]))`
- 错误率：`sum(rate(fastapi_request_total{status_code=~"5.."}[5m])) / sum(rate(fastapi_request_total[5m]))`
- P95 耗时：`histogram_quantile(0.95, sum(rate(fastapi_request_duration_seconds_bucket[5m])) by (le))`
- ready 状态：`fastapi_runtime_ready`
- 日志缓冲失败：`sum(rate(fastapi_log_buffer_flush_total{failed="true"}[5m])) by (reason)`，配合积压面板 `fastapi_log_buffer_pending_items`
- 审计写失败：`sum(increase(fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}[5m]))`
- 任务失败率：`sum(rate(fastapi_task_execution_total{outcome="failed"}[10m])) by (task_name) / sum(rate(fastapi_task_execution_total[10m])) by (task_name)`
- 资源饱和度：`fastapi_runtime_saturation_ratio`，按 `resource` 标签分面展示线程池、数据库连接池、任务队列与日志缓冲
- Codex 客户端错误：`sum(rate(fastapi_codex_client_diagnostic_total{outcome="recorded"}[5m])) by (source,error_code)`；被限流事件使用 `outcome="rate_limited"` 单独观察，避免将客户端重试误判为服务端错误
- Codex 客户端性能样本量：`sum(rate(fastapi_codex_client_performance_sample_total[5m])) by (metric,observation)`
- Codex 客户端最新性能值：`fastapi_codex_client_performance_value`，必须先按固定 `metric` 筛选，不能跨单位做数学比较

## Codex 专项面板边界

当前可直接落地的 Codex 面板包括客户端错误速率、按来源/受限错误码的错误分布、诊断限流抑制率，以及按固定测量和观测值聚合的性能样本量。错误和性能诊断事件均使用既有结构化日志缓冲写入 `app_log_record`；错误记录由 `CodexControlRuntime` 的周期任务在 14 天后删除，性能样本在 30 天后删除。清理任务不保存删除游标，重复或多实例执行只会删除同一时间条件下剩余记录。

性能词表已固定覆盖滚动状态转换、意外 detach、锚点修正、batch 大小、Reducer/Markdown 耗时、长任务、近似 FPS、发送 ack、重复操作、重连原因、cursor gap、snapshot replay、认证终态、stalled、审批交付和 PWA 遗留 controller。时间线滚动控制器已在内存中测量状态转换和锚点修正；实时连接路径已在内存中测量 batch 事件数、Reducer 耗时、重连原因、cursor gap 和认证终态；PWA 退场插件仅在检测到仍控制当前页的遗留 controller 时记录固定计数，不保留 scope、缓存名或 URL。服务端只接收 `POST /codex/diagnostics/performance` 的严格 Pydantic 信封，且 `client_diagnostic_performance_collection_enabled=false` 时确认接收但不记录。前端收集器只在当前标签页内存中构造通过固定 10% 会话采样的信封，没有 HTTP、WebSocket、Storage、Service Worker 或自动上传路径。

开发栈已验证 Prometheus 抓取应用 `/metrics`、Grafana 数据源/面板 provisioning，以及 Alertmanager smoke alert 的 firing/recovery；这不等同于真实浏览器产生 FPS、重连或审批性能样本，也不等同于生产监控部署。只有在显式启用传输开关并完成跨实例限流、留存和浏览器端到端验证后，才能将性能值用于生产告警阈值。

## 日志刷盘语义

`flush_interval_seconds` 是日志缓冲的 lazy flush 阈值：新日志进入 `LogBufferDispatcher.emit()` 时，若距离上次刷盘已超过该间隔，会在本次 emit 路径触发批量刷盘。它不是后台定时线程；没有新日志进入时，不会仅因时间到达自动刷盘。

审计关键事件（`persistence_priority = audit_critical`，覆盖管理员身份/scope/role 变更、配置热更新与安全配置拒绝）不进入缓冲：`emit()` 在发射线程内以 `reason="audit_critical"` 同步提交写请求，返回前即进入数据库事务提交路径，因此进程被强制终止不会丢失此类事件；写失败计入 `AuditWriteFailureCounter` 失败快照并反映到 `fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}`。

资源生命周期会显式收口日志缓冲：运行时关闭时执行 shutdown/manual flush，手动刷盘入口也会立即落库。日志缓冲积压与失败已通过 `fastapi_log_buffer_pending_items` 与 `fastapi_log_buffer_flush_total` 暴露，Grafana/Prometheus 不直接读取日志缓冲内容。

## 敏感信息约束

指标标签只使用低基数值：HTTP 方法、FastAPI 低基数路由模板、状态码、封闭枚举取值（安全事件类型/决策/级别、刷盘原因、任务结果、资源名、Codex 错误诊断来源/受限错误码/结果、Codex 性能测量/观测）与任务注册名，不记录完整 URL、请求体、Authorization、JWT、password、secret 或 token。动态主流程路由会记录 `/users/{subject_id}` 这类 route template；无法解析模板或疑似原始动态路径时统一归入 `unknown`。安全事件指标执行白名单策略：事件类型不属于 `SecurityEventType` 封闭枚举时不打点；Codex 错误诊断指标只消费服务端重建后的已知错误码，性能指标只消费固定词表及其匹配的单位和有限数值。
