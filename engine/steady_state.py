from typing import List, Dict, Any
import statistics

METRICS = ['sbp', 'dbp', 'pp', 'hr']

# 多窗口尺度：随着数据积累，逐级解锁更大、更稳定的近期窗口
# 与 language.py 的 _get_window（"30pt" > "20pt" > "10pt" > "5pt" > "3pt"）一一对应
WINDOW_SIZES = [3, 5, 10, 20, 30]

# 变点检测参数（用于真实的多分段，而不是恒为1段的"global"）
SEGMENT_ROLL_WINDOW = 3       # 滚动中位数窗口
SEGMENT_SHIFT_THRESHOLD = 10.0  # 持续偏移多少 mmHg 才算"结构性切段"
SEGMENT_MIN_RECORDS = 6        # 少于这个数据量，不做变点检测，整体作为一段


def _get_sort_key(x):
    return x.get('datetime') or x.get('timestamp') or ""


def _get_profile(records: List[Dict]) -> Dict[str, Any]:
    """
    计算一组记录的统计画像 (Median, Mean, Min, Max, IQR)
    """
    if not records:
        return {}

    for r in records:
        if "pp" not in r and "sbp" in r and "dbp" in r:
            r["pp"] = r["sbp"] - r["dbp"]

    profile = {}
    for key in METRICS:
        values = [r.get(key) for r in records if r.get(key) is not None]
        if not values:
            continue
        try:
            median_val = statistics.median(values)
            mean_val = statistics.mean(values)
            min_val = min(values)
            max_val = max(values)
            iqr = 0
            if len(values) >= 2:
                qs = statistics.quantiles(values, n=4)
                iqr = qs[2] - qs[0]
            profile[key] = {
                "median": median_val,
                "mean": mean_val,
                "min": min_val,
                "max": max_val,
                "iqr": iqr,
            }
        except Exception:
            continue

    return profile


def _stability_score(profile: Dict[str, Any]) -> float:
    """
    用 SBP 的 IQR 归一化出一个 0~1 的稳定性分数：IQR 越小越稳定。
    30mmHg 及以上视为最不稳定（分数记0）。
    """
    sbp_iqr = profile.get('sbp', {}).get('iqr', 0) or 0
    return round(max(0.0, 1.0 - min(sbp_iqr, 30.0) / 30.0), 3)


def _segment_records(sorted_records: List[Dict]) -> List[List[Dict]]:
    """
    真实变点检测（替代原来恒为1段的"global"实现）：
    - 用固定长度的滚动 SBP 中位数序列，检测是否出现"持续性、结构性"的偏移
    - 只有当新的滚动中位数相对当前分段基准持续偏移 >= SEGMENT_SHIFT_THRESHOLD
      并且这种偏移维持了至少 SEGMENT_ROLL_WINDOW 个连续点时，才切出新分段
      （避免单次波动被误判为"结构性变化"，符合"看轨迹不看单点"的原则）
    - 数据量不足时，整体作为一段，与原逻辑保持兼容
    """
    n = len(sorted_records)
    if n < SEGMENT_MIN_RECORDS:
        return [sorted_records]

    w = SEGMENT_ROLL_WINDOW
    sbp_values = [r.get('sbp') for r in sorted_records]

    rolling = []
    for i in range(n):
        lo = max(0, i - w + 1)
        chunk = [v for v in sbp_values[lo:i + 1] if v is not None]
        rolling.append(statistics.median(chunk) if chunk else None)

    boundaries = [0]
    seg_baseline = rolling[w - 1] if rolling[w - 1] is not None else rolling[0]
    consecutive_shift = 0

    for i in range(w, n):
        if rolling[i] is None or seg_baseline is None:
            continue
        if abs(rolling[i] - seg_baseline) >= SEGMENT_SHIFT_THRESHOLD:
            consecutive_shift += 1
        else:
            consecutive_shift = 0

        if consecutive_shift >= w:
            new_start = i - w + 1
            if new_start > boundaries[-1]:
                boundaries.append(new_start)
            seg_baseline = rolling[i]
            consecutive_shift = 0

    boundaries.append(n)
    segments = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if end > start:
            segments.append(sorted_records[start:end])

    return segments if segments else [sorted_records]


def analyze_steady_states(records: List[Dict]) -> Dict[str, Any]:
    """
    稳态分析：多窗口轨迹 + 真实多分段结构变化检测。
    """
    if not records:
        return {}

    sorted_records = sorted(records, key=_get_sort_key)
    n = len(sorted_records)

    is_personalized = n >= 5
    records_needed = max(0, 5 - n)

    # 1. 基线：固定取前 30%（至少3条）作为长期参照，所有窗口共用同一个基线
    if n < 5:
        baseline_recs = sorted_records
    else:
        split_idx = max(3, int(n * 0.3))
        baseline_recs = sorted_records[:split_idx]

    base_profile = _get_profile(baseline_recs)
    base_stability = _stability_score(base_profile)

    # 2. 多窗口：逐级取最近 N 条与基线比较，解锁多步轨迹
    windows: Dict[str, Any] = {}
    trajectory: Dict[str, List[Dict[str, Any]]] = {m: [] for m in METRICS}
    largest_label = None

    for w in WINDOW_SIZES:
        if n < w:
            continue
        label = f"{w}pt"
        largest_label = label  # WINDOW_SIZES 递增，最后一次赋值即最大可用窗口

        recent_recs = sorted_records[-w:]
        recent_profile = _get_profile(recent_recs)
        recent_stability = _stability_score(recent_profile)

        windows[label] = {
            "baseline": {
                "start": baseline_recs[0].get("datetime"),
                "end": baseline_recs[-1].get("datetime"),
                "profile": base_profile,
                "stability": base_stability,
            },
            "recent": {
                "start": recent_recs[0].get("datetime"),
                "end": recent_recs[-1].get("datetime"),
                "profile": recent_profile,
                "stability": recent_stability,
            },
        }

        for m in METRICS:
            if m not in base_profile or m not in recent_profile:
                continue
            base_val = base_profile[m]['median']
            recent_val = recent_profile[m]['median']
            delta = recent_val - base_val
            status = "stable"
            if delta >= 5:
                status = "up"
            elif delta <= -5:
                status = "down"
            trajectory[m].append({
                "window": label,
                "delta": delta,
                "status": status,
                "base": base_val,
                "recent": recent_val,
            })

    # 数据量太小（< 3），一个窗口都生成不了时，保底一个 general 窗口，避免下游拿到空结构
    if not windows:
        recent_profile = _get_profile(sorted_records)
        windows["general"] = {
            "baseline": {
                "start": baseline_recs[0].get("datetime"),
                "end": baseline_recs[-1].get("datetime"),
                "profile": base_profile,
                "stability": base_stability,
            },
            "recent": {
                "start": sorted_records[0].get("datetime"),
                "end": sorted_records[-1].get("datetime"),
                "profile": recent_profile,
                "stability": _stability_score(recent_profile),
            },
        }

    # 3. 供 risk_level.py 使用的简化趋势：取当前可用的最大窗口
    trend_simple = {}
    for m in METRICS:
        steps = trajectory.get(m, [])
        match = next((s for s in steps if s["window"] == largest_label), None)
        trend_simple[m] = match["status"] if match else "stable"

    # 4. 真实多分段（供 emergency.py 的"稳态失稳"、timeline.py 使用）
    seg_chunks = _segment_records(sorted_records)
    segments = []
    for chunk in seg_chunks:
        prof = _get_profile(chunk)
        segments.append({
            "start": chunk[0].get("datetime"),
            "end": chunk[-1].get("datetime"),
            "count": len(chunk),
            "type": "segment",
            "profile": prof,
            "stability": _stability_score(prof),
        })

    # 5. 个体化稳态带（不变）
    sbp_median = base_profile.get("sbp", {}).get("median", 120)
    sbp_iqr = base_profile.get("sbp", {}).get("iqr", 10)
    sbp_margin = max(sbp_iqr * 1.5, 15.0)
    band = {
        "sbp_upper": sbp_median + sbp_margin,
        "sbp_lower": sbp_median - sbp_margin,
        "margin": sbp_margin,
        "is_personalized": is_personalized,
        "records_needed": records_needed,
    }

    # 6. 症状聚合：取当前可用的最大窗口对应的记录范围（没有窗口时退回全部记录）
    if largest_label:
        w_size = int(largest_label.replace("pt", ""))
        symptom_scope = sorted_records[-w_size:]
    else:
        symptom_scope = sorted_records

    all_symptoms = []
    for r in symptom_scope:
        syms = r.get("symptoms", []) or r.get("events", [])
        if isinstance(syms, list):
            all_symptoms.extend(syms)
    unique_symptoms = list(set(all_symptoms))
    events_by_segment = [unique_symptoms] if unique_symptoms else []

    return {
        "segments": segments,
        "events_by_segment": events_by_segment,
        "trajectory": trajectory,
        "windows": windows,
        "base": {
            "sbp": base_profile.get("sbp", {}).get("median", 120),
            "dbp": base_profile.get("dbp", {}).get("median", 80),
            "pp": base_profile.get("pp", {}).get("median", 40),
            "band": band,
        },
        "trend": trend_simple,
    }
