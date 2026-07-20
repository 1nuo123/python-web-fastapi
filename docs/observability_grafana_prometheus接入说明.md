# Grafana 与 Prometheus 接入说明

## 当前边界

当前项目只补应用侧可观测性接入点，不内置 Prometheus、Grafana、Loki、Tempo、Promtail、Alertmanager 部署栈。

- OpenTelemetry：配置与 FastAPI instrument 桥接已保留，默认关闭。
- Prometheus：通过 `runtime.metrics.header.enabled` 控制是否暴露 `/metrics`。
- Grafana：不直接接入应用代码，通过 Prometheus 数据源展示应用指标。

## 应用配置

```toml
[runtime.header]
enabled = true

[runtime.detail]
metrics_path = "/metrics"
include_http_metrics = true
include_runtime_metrics = true
```

`/metrics` 使用 Prometheus 文本格式返回，不使用项目统一 JSON 响应信封。

## Prometheus 抓取示例

```yaml
scrape_configs:
  - job_name: fastapi-web-skeleton
    metrics_path: /metrics
    static_configs:
      - targets: ["app:8000"]
```

本地开发没有启动 Prometheus 的强制要求。只有部署监控系统时，才需要把目标地址替换为实际应用服务名和端口。

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

## 首批面板建议

- QPS：`sum(rate(fastapi_request_total[5m]))`
- 错误率：`sum(rate(fastapi_request_total{status_code=~"5.."}[5m])) / sum(rate(fastapi_request_total[5m]))`
- P95 耗时：`histogram_quantile(0.95, sum(rate(fastapi_request_duration_seconds_bucket[5m])) by (le))`
- ready 状态：`fastapi_runtime_ready`
- 日志缓冲失败数：当前应用未输出该指标，后续如新增日志缓冲指标再补面板。

## 日志刷盘语义

`flush_interval_seconds` 是日志缓冲的 lazy flush 阈值：新日志进入 `LogBufferDispatcher.emit()` 时，若距离上次刷盘已超过该间隔，会在本次 emit 路径触发批量刷盘。它不是后台定时线程；没有新日志进入时，不会仅因时间到达自动刷盘。

资源生命周期会显式收口日志缓冲：运行时关闭时执行 shutdown/manual flush，手动刷盘入口也会立即落库。Grafana/Prometheus 不直接读取日志缓冲内容，若后续需要展示日志缓冲积压、失败数或刷盘延迟，应先在应用侧新增低基数指标，再配置面板。

## 敏感信息约束

指标标签只使用 HTTP 方法、FastAPI 低基数路由模板和状态码，不记录完整 URL、请求体、Authorization、JWT、password、secret 或 token。动态主流程路由会记录 `/users/{subject_id}` 这类 route template；无法解析模板或疑似原始动态路径时统一归入 `unknown`。
