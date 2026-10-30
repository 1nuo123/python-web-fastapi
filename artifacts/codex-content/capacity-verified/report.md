# 容量搜索结果

真实 TCP/Uvicorn/websockets、产品单写者和正文读取器；源为受控缓存，未模拟官方 CLI 的超大单项范围 API。

|完整块预算|通过轮数|最低吞吐 MiB/s|最高控制 P95 ms|最高排队字节|
|---|---:|---:|---:|---:|
|16384|20|3.196|2.223|11339|
|32768|20|4.167|3.343|20845|
|65536|20|10.469|2.828|40320|

过滤配置：3 组；不能容纳一页的在途预算被淘汰。

16 KiB 的最低吞吐已超过 4 MiB/s；较大块提高吞吐，同时增加队列峰值。正文读取路线值得保留。没有吞吐收益证据支持增加 page/inflight，因此这两维不能按本实验排名。

全系统默认保留 page=128 KiB / chunk=16 KiB / inflight=256 KiB：允许同时容纳两个历史页，并以完整产品 HTTPS/WSS 场景验证。性能激进配置不自动晋升；缺少真实多主机、远程网络和浏览器 heap 的对照证据。

Held-out 结果：
```json
{
  "config": {
    "chunk": 65536,
    "page": 262144,
    "inflight": 262144
  },
  "seed": 97,
  "profile": "slow_receiver",
  "passed": true,
  "source": "synthetic bounded cache; NOT official CLI range support",
  "total_bytes": 9437380,
  "seconds": 0.8570661999983713,
  "mib_per_second": 10.501157227041643,
  "chunks": 288,
  "max_message_bytes": 39980,
  "control_p50_ms": 2.1608999959426,
  "control_p95_ms": 2.791800012346357,
  "control_p99_ms": 3.0584000051021576,
  "queue_peak_bytes": 39980,
  "cache_bytes": 9438117,
  "rss_bytes": 101982208,
  "sha256": "ad715df4ef67800c32571c1b37f51a3aee04a92939a94243ffa6d19a00f4cf5f"
}
```
