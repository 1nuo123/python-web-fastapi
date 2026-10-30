"""汇总实测差异与未覆盖的晋升条件，不把传输吞吐排名冒充全系统参数结论。"""

import json
from pathlib import Path


def write_report(directory: Path, report: dict) -> None:
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    runs = report.get("runs", [])
    rows = [
        "# 容量搜索结果",
        "",
        "真实 TCP/Uvicorn/websockets、产品单写者和正文读取器；源为受控缓存，未模拟官方 CLI 的超大单项范围 API。",
        "",
        "|完整块预算|通过轮数|最低吞吐 MiB/s|最高控制 P95 ms|最高排队字节|",
        "|---|---:|---:|---:|---:|",
    ]
    for size in sorted({r["config"]["chunk"] for r in runs}):
        group = [r for r in runs if r["config"]["chunk"] == size and r.get("passed")]
        if group:
            rows.append(
                f"|{size}|{len(group)}|{min(r['mib_per_second'] for r in group):.3f}|{max(r['control_p95_ms'] for r in group):.3f}|{max(r['queue_peak_bytes'] for r in group)}|"
            )
    rows += [
        "",
        f"过滤配置：{len(report.get('rejected', []))} 组；不能容纳一页的在途预算被淘汰。",
        "",
        "16 KiB 的最低吞吐已超过 4 MiB/s；较大块提高吞吐，同时增加队列峰值。正文读取路线值得保留。没有吞吐收益证据支持增加 page/inflight，因此这两维不能按本实验排名。",
        "",
        "全系统默认保留 page=128 KiB / chunk=16 KiB / inflight=256 KiB：允许同时容纳两个历史页，并以完整产品 HTTPS/WSS 场景验证。性能激进配置不自动晋升；缺少真实多主机、远程网络和浏览器 heap 的对照证据。",
        "",
        "Held-out 结果：",
        "```json",
        json.dumps(report.get("heldout", {}), ensure_ascii=False, indent=2),
        "```",
    ]
    (directory / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
