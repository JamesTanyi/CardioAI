from typing import Dict, Any, List

METRICS = ["sbp", "dbp", "pp", "hr"]


def analyze_structure_shift(steady_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    基于稳态分析结果，判断是否存在“结构性重塑”：
    - 不做诊断，只描述“模式是否发生了持续性改变”
    - 结合方向（up/down）和幅度（delta 大小）
    """
    trajectory: Dict[str, List[Dict[str, Any]]] = steady_result.get("trajectory", {})
    if not trajectory:
        return {
            "shift_level": "UNKNOWN",
            "dimensions": [],
            "pattern": "",
            "details": {},
        }

    dimensions: List[str] = []
    pattern_parts: List[str] = []
    details: Dict[str, Any] = {}

    # 你可以根据数据调整这个阈值：
    # 例如：平均 delta 超过 5，才认为是“有意义的结构变化”
    MEAN_DELTA_THRESHOLD = 5.0
    MIN_STEPS_FOR_JUDGEMENT = 2  # 至少有两个窗口对比，才谈“趋势”

    for m in METRICS:
        steps = trajectory.get(m, [])
        if not steps or len(steps) < MIN_STEPS_FOR_JUDGEMENT:
            continue

        statuses = [s["status"] for s in steps]
        deltas = [s["delta"] for s in steps]

        avg_delta = sum(deltas) / len(deltas)
        up_count = statuses.count("up")
        down_count = statuses.count("down")

        # 保存详细轨迹，方便后续解释
        details[m] = {
            "statuses": statuses,
            "deltas": deltas,
            "avg_delta": avg_delta,
            "up_count": up_count,
            "down_count": down_count,
        }

        # 判断该维度是否存在“结构性变化”
        # 条件：方向相对一致 + 平均变化幅度足够大
        if abs(avg_delta) >= MEAN_DELTA_THRESHOLD:
            if up_count >= down_count:
                # 以“整体偏上”为主
                dimensions.append(m)
                pattern_parts.append(f"{m.upper()}↑")
            else:
                dimensions.append(m)
                pattern_parts.append(f"{m.upper()}↓")

    # 结构重塑等级
    if not dimensions:
        shift_level = "NO_REMODELING"
    elif len(dimensions) == 1:
        shift_level = "MONO_DIMENSION_REMODELING"
    elif len(dimensions) == 2:
        shift_level = "BI_DIMENSION_REMODELING"
    else:
        shift_level = "MULTI_DIMENSION_REMODELING"

    pattern = " + ".join(pattern_parts) if pattern_parts else "none"

    return {
        "shift_level": shift_level,
        "dimensions": dimensions,
        "pattern": pattern,
        "details": details,
    }
