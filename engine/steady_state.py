from typing import List, Dict, Any
from datetime import timedelta
import statistics

METRICS = ['sbp', 'dbp', 'pp', 'hr']

# 多窗口尺度：随着数据积累，逐级解锁更大、更稳定的近期窗口
# 与 language.py 的 _get_window（"30pt" > "20pt" > "10pt" > "5pt" > "3pt"）一一对应
WINDOW_SIZES = [3, 5, 10, 20, 30]

# ★ 新增：日历天窗口——跟上面WINDOW_SIZES(按点数)是两套完全不同的东西。
#   WINDOW_SIZES服务"多步轨迹"这类需要固定点数对比的场景；这里的日历天窗口
#   服务三角色语言层的趋势描述："最近14天 vs 再往前14天"，不管这14天里
#   到底测了几次，都是按自然日期切的，跟测量频率无关。
CALENDAR_WINDOWS = [14, 28]

# 变点检测参数（用于真实的多分段，而不是恒为1段的"global"）
SEGMENT_ROLL_WINDOW = 3         # 滚动中位数窗口
SEGMENT_SHIFT_THRESHOLD = 10.0  # SBP持续偏移多少mmHg才算候选"结构性切段"
SEGMENT_DBP_SHIFT = 6.0         # DBP同步偏移阈值(供置信度里的"多指标同步"判断)
SEGMENT_HR_SHIFT = 8.0          # HR同步偏移阈值(同上)
SEGMENT_MIN_RECORDS = 6         # 少于这个数据量，不做变点检测，整体作为一段

# ★ 新增：置信度融合分段的参数——替代原来"点数达标就切"的判定方式。
#   一个候选切点要不要真正确认成新分段，看两件事融合后的置信度：
#   ①这段候选区间的"日历天数"和"测量次数"分别达标到什么程度(避免"两天
#   狂测6次就确认新基线"这种漏洞，也避免"按周测的人永远攒不够点数"这种滞后)；
#   ②SBP的偏移有没有HR/PP同步佐证(只有SBP自己动、HR/PP没反应，更可能是
#   白大衣效应或偶然波动；三个指标同步偏移，才更像是真实的结构性变化)。
SEGMENT_TARGET_DAYS = 14        # 候选区间日历天跨度达到这个数，时间置信度里的"天数"部分给满分
SEGMENT_TARGET_COUNT = 6        # 候选区间测量次数达到这个数，时间置信度里的"次数"部分给满分
SEGMENT_TIME_WEIGHT = 0.6       # 时间置信度在总置信度里的权重
SEGMENT_SYNC_WEIGHT = 0.4       # 多指标同步置信度在总置信度里的权重
SEGMENT_CONFIRM_THRESHOLD = 0.7 # 总置信度达到这个数才真正确认新分段
SEGMENT_ABANDON_MULTIPLIER = 4  # 一个候选切点持续攒了 w*这个倍数 个点还凑不够置信度，放弃这次候选，避免死等

# ★ 新增：每个指标的band参数——min_margin是原来就有的"下限保底"(避免IQR过小
#   导致band窄到一点点噪声都被判成异常)，max_margin是新增的"上限封顶"(避免
#   IQR过大——比如本身波动就大的人——导致band宽到失去预警意义，怎么测都测不出偏离)。
METRIC_BAND_PARAMS = {
    'sbp': {'min_margin': 15.0, 'max_margin': 60.0},
    'dbp': {'min_margin': 10.0, 'max_margin': 40.0},
    'hr':  {'min_margin': 10.0, 'max_margin': 30.0},
    'pp':  {'min_margin': 10.0, 'max_margin': 40.0},
}


def _get_sort_key(x):
    return x.get('datetime') or x.get('timestamp') or ""


def _get_profile(records: List[Dict]) -> Dict[str, Any]:
    """
    计算一组记录的统计画像 (Median, Mean, Min, Max, IQR, Q1, Q3)
    ★ 改：新增q1/q3两个字段——原来只存iqr(q3-q1的差值)，现在的非对称band
    需要知道q1、q3各自的具体位置，不能只有差值。
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
            q1, q3 = median_val, median_val
            iqr = 0
            if len(values) >= 2:
                qs = statistics.quantiles(values, n=4)
                q1, q3 = qs[0], qs[2]
                iqr = q3 - q1
            profile[key] = {
                "median": median_val,
                "mean": mean_val,
                "min": min_val,
                "max": max_val,
                "iqr": iqr,
                "q1": q1,
                "q3": q3,
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


def _build_band(profile: Dict[str, Any], metric: str) -> Dict[str, Any]:
    """
    ★ 新增：单个指标的非对称band——中线用median，上下宽度分别根据
    该指标到Q3/Q1的距离算(乘1.5，参照Tukey栅栏思路)，但不再强制对称，
    分布本身偏态时(比如晨峰型，向上偏得多向下偏得少)，上下宽度会自然不同。
    同时加了min_margin(下限保底，避免过窄)和max_margin(上限封顶，避免过宽
    到失去预警意义)两层夹逼。
    """
    p = profile.get(metric, {})
    median = p.get("median")
    if median is None:
        return None

    params = METRIC_BAND_PARAMS.get(metric, {'min_margin': 15.0, 'max_margin': 60.0})
    min_margin = params['min_margin']
    max_margin = params['max_margin']

    q1 = p.get("q1", median - min_margin)
    q3 = p.get("q3", median + min_margin)

    raw_upper_width = (q3 - median) * 1.5
    raw_lower_width = (median - q1) * 1.5

    upper_width = max(min_margin, min(max_margin, raw_upper_width if raw_upper_width > 0 else min_margin))
    lower_width = max(min_margin, min(max_margin, raw_lower_width if raw_lower_width > 0 else min_margin))

    return {
        "median": median,
        "upper": median + upper_width,
        "lower": median - lower_width,
        "upper_width": upper_width,
        "lower_width": lower_width,
    }


def _deviation_ratio(value, band) -> float:
    """
    ★ 新增：当前值偏离band的比例——供Path A分档直接用。
    <0.5 = 在band内层(低)；0.5~1.0 = 逼近band边缘(关注)；
    >=1.0 = 已经突破band(中)。往上偏和往下偏分别用upper_width/lower_width
    做分母，天然兼容非对称band。
    """
    if band is None or value is None:
        return 0.0
    median = band["median"]
    if value >= median:
        width = band["upper_width"] or 1.0
        return max(0.0, (value - median) / width)
    else:
        width = band["lower_width"] or 1.0
        return max(0.0, (median - value) / width)


def _time_confidence(days_span: int, record_count: int) -> float:
    """候选分段的'日历天数达标度'和'测量次数达标度'各算一半，加权融合。"""
    days_conf = min(1.0, days_span / SEGMENT_TARGET_DAYS) if SEGMENT_TARGET_DAYS else 1.0
    count_conf = min(1.0, record_count / SEGMENT_TARGET_COUNT) if SEGMENT_TARGET_COUNT else 1.0
    return 0.5 * days_conf + 0.5 * count_conf


def _sync_confidence(dbp_shift, hr_shift) -> float:
    """
    SBP的偏移有没有DBP/HR同步佐证——注意不能用PP，PP=SBP-DBP是算出来的，
    DBP不动时SBP自己涨，PP会机械性地跟着涨，不是真正独立的第二个信号。
    DBP和HR是两个真正独立测量的指标，2个里有1个同步偏移给0.5，2个都
    同步给满分1.0。
    """
    hits = 0
    if dbp_shift is not None and abs(dbp_shift) >= SEGMENT_DBP_SHIFT:
        hits += 1
    if hr_shift is not None and abs(hr_shift) >= SEGMENT_HR_SHIFT:
        hits += 1
    return hits / 2.0


def _rolling_median_series(values: List, w: int) -> List:
    n = len(values)
    rolling = []
    for i in range(n):
        lo = max(0, i - w + 1)
        chunk = [v for v in values[lo:i + 1] if v is not None]
        rolling.append(statistics.median(chunk) if chunk else None)
    return rolling


def _segment_records(sorted_records: List[Dict]) -> List[List[Dict]]:
    """
    真实变点检测 + 置信度融合确认（替代原来"点数达标就切"的实现）：
    - 用固定长度的滚动中位数序列(SBP/HR/PP三个都算)，检测SBP是否出现
      持续性偏移(候选切点)
    - 候选切点出现后，不再直接切段，而是算一个"置信度"：日历天数+测量
      次数的达标程度(时间置信度) 融合 HR/PP有没有同步偏移(同步置信度)，
      达到SEGMENT_CONFIRM_THRESHOLD才真正确认，否则继续观察，避免
      "两天狂测6次"或"只有SBP自己动"这两种情况被误判成结构性变化
    - 一个候选点持续观察太久还凑不够置信度，放弃这次候选，避免卡死
    """
    n = len(sorted_records)
    if n < SEGMENT_MIN_RECORDS:
        return [sorted_records]

    w = SEGMENT_ROLL_WINDOW
    sbp_values = [r.get('sbp') for r in sorted_records]
    hr_values = [r.get('hr') for r in sorted_records]
    dbp_values = [r.get('dbp') for r in sorted_records]

    rolling_sbp = _rolling_median_series(sbp_values, w)
    rolling_hr = _rolling_median_series(hr_values, w)
    rolling_dbp = _rolling_median_series(dbp_values, w)

    boundaries = [0]
    seg_start_idx = 0
    seg_baseline_sbp = rolling_sbp[w - 1] if rolling_sbp[w - 1] is not None else rolling_sbp[0]
    seg_baseline_hr = rolling_hr[w - 1] if rolling_hr[w - 1] is not None else rolling_hr[0]
    seg_baseline_dbp = rolling_dbp[w - 1] if rolling_dbp[w - 1] is not None else rolling_dbp[0]
    consecutive_shift = 0

    for i in range(w, n):
        if rolling_sbp[i] is None or seg_baseline_sbp is None:
            continue

        sbp_diff = rolling_sbp[i] - seg_baseline_sbp
        if abs(sbp_diff) >= SEGMENT_SHIFT_THRESHOLD:
            consecutive_shift += 1
        else:
            consecutive_shift = 0

        if consecutive_shift >= w:
            candidate_start = i - w + 1
            if candidate_start > boundaries[-1]:
                seg_start_date = sorted_records[seg_start_idx].get('datetime')
                cur_date = sorted_records[i].get('datetime')
                days_span = 0
                if seg_start_date and cur_date:
                    try:
                        days_span = max(0, (cur_date - seg_start_date).days)
                    except Exception:
                        days_span = 0
                record_count = i - seg_start_idx + 1

                hr_diff = (rolling_hr[i] - seg_baseline_hr) if (rolling_hr[i] is not None and seg_baseline_hr is not None) else None
                dbp_diff = (rolling_dbp[i] - seg_baseline_dbp) if (rolling_dbp[i] is not None and seg_baseline_dbp is not None) else None

                time_conf = _time_confidence(days_span, record_count)
                sync_conf = _sync_confidence(dbp_diff, hr_diff)
                confidence = SEGMENT_TIME_WEIGHT * time_conf + SEGMENT_SYNC_WEIGHT * sync_conf

                if confidence >= SEGMENT_CONFIRM_THRESHOLD:
                    boundaries.append(candidate_start)
                    seg_start_idx = candidate_start
                    seg_baseline_sbp = rolling_sbp[i]
                    seg_baseline_hr = rolling_hr[i]
                    seg_baseline_dbp = rolling_dbp[i]
                    consecutive_shift = 0
                elif consecutive_shift > w * SEGMENT_ABANDON_MULTIPLIER:
                    # 攒了很久还是凑不够置信度，放弃这次候选，避免永远卡在半路
                    consecutive_shift = 0

    boundaries.append(n)
    segments = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if end > start:
            segments.append(sorted_records[start:end])

    return segments if segments else [sorted_records]


def _calendar_window_profile(sorted_records: List[Dict], days: int) -> Dict[str, Any]:
    """
    ★ 新增：按日历天(不是按点数)截取最近N天的记录并算画像+极值。
    供三角色语言层的14d/28d趋势描述使用。
    """
    if not sorted_records:
        return {}
    latest_dt = sorted_records[-1].get('datetime')
    if not latest_dt:
        return {}
    try:
        cutoff = latest_dt - timedelta(days=days)
    except Exception:
        return {}
    subset = [r for r in sorted_records if r.get('datetime') and r.get('datetime') >= cutoff]
    if not subset:
        return {}
    profile = _get_profile(subset)
    return {
        "start": subset[0].get("datetime"),
        "end": subset[-1].get("datetime"),
        "count": len(subset),
        "profile": profile,
    }


def analyze_steady_states(records: List[Dict]) -> Dict[str, Any]:
    """
    稳态分析：多窗口轨迹 + 真实多分段结构变化检测(置信度融合) +
    14d/28d日历天动态趋势 + 多指标非对称band。
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

    # 3. 供 risk_level.py 使用的简化趋势：取当前可用的最大窗口（保留兼容旧调用方）
    trend_simple = {}
    for m in METRICS:
        steps = trajectory.get(m, [])
        match = next((s for s in steps if s["window"] == largest_label), None)
        trend_simple[m] = match["status"] if match else "stable"

    # 4. 真实多分段（置信度融合确认，供 emergency.py 的"稳态失稳"、timeline.py、
    #    医生报告使用）
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

    # 5. 多指标非对称band（SBP/DBP/HR/PP都算，不再只有SBP）+ 保留旧的band字段
    #    (只含sbp_upper/sbp_lower，供尚未升级的旧调用方兼容读取)
    bands = {m: _build_band(base_profile, m) for m in METRICS}
    sbp_band = bands.get('sbp')
    legacy_band = {
        "sbp_upper": sbp_band["upper"] if sbp_band else base_profile.get("sbp", {}).get("median", 120) + 15,
        "sbp_lower": sbp_band["lower"] if sbp_band else base_profile.get("sbp", {}).get("median", 120) - 15,
        "margin": sbp_band["upper_width"] if sbp_band else 15.0,
        "is_personalized": is_personalized,
        "records_needed": records_needed,
    }

    # 6. 当前最新一条记录相对各指标band的偏离比例，供Path A分档直接用
    latest = sorted_records[-1]
    latest_pp = latest.get("pp")
    if latest_pp is None and latest.get("sbp") is not None and latest.get("dbp") is not None:
        latest_pp = latest["sbp"] - latest["dbp"]
    latest_values = {
        "sbp": latest.get("sbp"),
        "dbp": latest.get("dbp"),
        "hr": latest.get("hr"),
        "pp": latest_pp,
    }
    current_deviation = {
        m: round(_deviation_ratio(latest_values.get(m), bands.get(m)), 3) for m in METRICS
    }

    # 7. ★ 新增：14d/28d日历天动态趋势——供三角色语言层用，不是"绝对高低数字"，
    #    是"最近14天 vs 再往前14天"这种滚动对比，天然贴合"讲趋势不讲结论"。
    dynamic_trend = {}
    calendar_profiles = {}
    for days in CALENDAR_WINDOWS:
        calendar_profiles[days] = _calendar_window_profile(sorted_records, days)

    win_short = calendar_profiles.get(CALENDAR_WINDOWS[0], {})   # 14d
    win_long = calendar_profiles.get(CALENDAR_WINDOWS[1], {})    # 28d
    for m in METRICS:
        p_short = win_short.get("profile", {}).get(m)
        p_long = win_long.get("profile", {}).get(m)
        if not p_short or not p_long:
            continue
        dynamic_trend[m] = {
            "recent_median": p_short["median"],
            "prior_median": p_long["median"],
            "delta": p_short["median"] - p_long["median"],
            "recent_max": p_short["max"],
            "recent_min": p_short["min"],
        }

    # 8. 症状聚合：取当前可用的最大窗口对应的记录范围（没有窗口时退回全部记录）
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
            "band": legacy_band,  # 兼容旧调用方（只有sbp_upper/sbp_lower）
        },
        "trend": trend_simple,       # 兼容旧调用方，risk_level.py重写后会改用bands/current_deviation
        "bands": bands,               # ★ 新增：sbp/dbp/hr/pp各自的非对称band
        "current_deviation": current_deviation,  # ★ 新增：最新一条记录相对各band的偏离比例
        "dynamic_trend": dynamic_trend,  # ★ 新增：14d vs 28d 滚动对比，供语言层用
        "calendar_windows": calendar_profiles,   # ★ 新增：14d/28d原始画像(含极值)，供语言层需要更细节时取用
    }