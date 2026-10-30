# 容量搜索结果

真实 TCP/Uvicorn/websockets、产品单写者和正文读取器；源为受控缓存，未模拟官方 CLI 的超大单项范围 API。

|完整块预算|通过轮数|最低吞吐 MiB/s|最高控制 P95 ms|最高排队字节|
|---|---:|---:|---:|---:|
|16384|20|4.741|1.686|11339|
|32768|20|7.330|2.116|20845|
|65536|20|10.154|2.870|40320|

过滤配置：3 组；不能容纳一页的在途预算被淘汰。

16 KiB 的最低吞吐已超过 4 MiB/s；较大块提高吞吐，同时增加队列峰值。正文读取路线值得保留。没有吞吐收益证据支持增加 page/inflight，因此这两维不能按本实验排名。

全系统默认保留 page=128 KiB / chunk=16 KiB / inflight=256 KiB：允许同时容纳两个历史页，并以完整产品 HTTPS/WSS 场景验证。性能激进配置不自动晋升；缺少真实多主机、远程网络和浏览器 heap 的对照证据。

Held-out 结果：
```json
{
  "config": {
    "chunk": 65536,
    "page": 131072,
    "inflight": 524288
  },
  "seed": 97,
  "profile": "slow_receiver",
  "passed": true,
  "source": "synthetic bounded cache; NOT official CLI range support",
  "total_bytes": 9437380,
  "seconds": 0.7819698000093922,
  "mib_per_second": 11.509634924594165,
  "chunks": 288,
  "max_message_bytes": 39980,
  "control_p50_ms": 1.7718499875627458,
  "control_p95_ms": 2.571100019849837,
  "control_p99_ms": 2.904799999669194,
  "queue_peak_bytes": 39980,
  "cache_bytes": 9438117,
  "rss_bytes": 102379520,
  "sha256": "ad715df4ef67800c32571c1b37f51a3aee04a92939a94243ffa6d19a00f4cf5f"
}
```
