"""硬约束先于延迟排序，缺失验证不能伪装成发布通过。"""

import math


def evaluate(result: dict) -> dict:
    durations = sorted(result.get("recovery_seconds", []))
    passed = (
        bool(result.get("passed"))
        and not result.get("execution_misstops", 0)
        and not result.get("sampling_gaps")
    )
    p95 = durations[math.ceil(len(durations) * 0.95) - 1] if durations else None
    p99 = durations[math.ceil(len(durations) * 0.99) - 1] if durations else None
    passed = passed and p95 is not None and p95 <= 10 and p99 <= 20
    return {
        "screening_passed": passed,
        "p95_seconds": durations[math.ceil(len(durations) * 0.95) - 1] if durations else None,
        "p99_seconds": durations[math.ceil(len(durations) * 0.99) - 1] if durations else None,
        "peak_rss_bytes": result.get("peak_rss_bytes"),
        "production_eligible": False,
        "conclusion": "continue full fault matrix and 12-hour soak"
        if passed
        else "reject configuration or repair failure before expanding",
    }
