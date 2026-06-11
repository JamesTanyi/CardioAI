from typing import List, Dict, Any
import statistics

def _get_profile(records: List[Dict]) -> Dict[str, Any]:
    """
    计算一组记录的统计画像 (Median, Mean, Min, Max, IQR)
    """
    if not records:
        return {}
    
    profile = {}
    # 确保只要有 sbp/dbp 就计算 pp
    for r in records:
        if "pp" not in r and "sbp" in r and "dbp" in r:
            r["pp"] = r["sbp"] - r["dbp"]

    for key in ['sbp', 'dbp', 'pp', 'hr']:
        values = [r.get(key) for r in records if r.get(key) is not None]
        if not values:
            continue
        
        # 计算统计量
        try:
            median_val = statistics.median(values)
            mean_val = statistics.mean(values)
            min_val = min(values)
            max_val = max(values)
            # 简单的波动性指标
            iqr = 0
            if len(values) >= 2:
                qs = statistics.quantiles(values, n=4)
                iqr = qs[2] - qs[0]
                
            profile[key] = {
                "median": median_val,
                "mean": mean_val,
                "min": min_val,
                "max": max_val,
                "iqr": iqr
            }
        except Exception:
            continue
            
    return profile

def analyze_steady_states(records: List[Dict]) -> Dict[str, Any]:
    """
    稳态分析：基于真实历史数据的基线与趋势计算
    """
    if not records:
        return {}

    # 1. 预处理：按时间排序
    # 兼容 datetime 对象或 timestamp 字符串
    def _get_sort_key(x):
        return x.get('datetime') or x.get('timestamp') or ""
    
    sorted_records = sorted(records, key=_get_sort_key)
    n = len(sorted_records)

    # 2. 窗口划分策略 (Baseline vs Recent)
    # 逻辑：如果没有足够数据，基线和近期重叠；否则取头部做基线，尾部做近期
    is_personalized = n >= 5 # 至少需要5条数据才算个性化
    records_needed = max(0, 5 - n) # 距离解锁个性化分析还差多少条
    if n < 5:
        baseline_recs = sorted_records
        recent_recs = sorted_records
    else:
        # 基线：取前 30% 数据，至少 3 条
        split_idx = max(3, int(n * 0.3))
        baseline_recs = sorted_records[:split_idx]
        # 近期：取最后 5 条数据
        recent_recs = sorted_records[-min(5, n):]

    # 3. 计算画像
    base_profile = _get_profile(baseline_recs)
    recent_profile = _get_profile(recent_recs)
    global_profile = _get_profile(sorted_records)

    # 4. 计算轨迹与趋势 (Trajectory & Trend)
    trajectory = {}
    trend_simple = {} # 供 risk_level.py 使用的简化趋势
    
    for key in ['sbp', 'dbp', 'pp', 'hr']:
        if key not in base_profile or key not in recent_profile:
            continue
            
        base_val = base_profile[key]['median']
        recent_val = recent_profile[key]['median']
        delta = recent_val - base_val
        
        # 趋势判定阈值
        status = "stable"
        if delta >= 5: status = "up"
        elif delta <= -5: status = "down"
        
        # 构造 structure_shift.py 所需的详细轨迹
        trajectory[key] = [{
            "window": "general", 
            "delta": delta,
            "status": status,
            "base": base_val,
            "recent": recent_val
        }]
        
        # 构造 risk_level.py 所需的简化趋势
        trend_simple[key] = status

    # 6. ⭐ 核心修复：计算个体化稳态带 (Individual Steady State Band)
    # 逻辑：中位数 ± (1.5倍IQR 或 最小阈值)
    # 如果用户波动大(IQR大)，带就宽；波动小，带就窄。但不能窄于 15mmHg(避免误报)
    sbp_median = base_profile.get("sbp", {}).get("median", 120)
    sbp_iqr = base_profile.get("sbp", {}).get("iqr", 10)
    # 最小带宽保护：15mmHg，防止对于极其稳定的用户，稍微波动一点就报警
    sbp_margin = max(sbp_iqr * 1.5, 15.0)
    
    band = {
        "sbp_upper": sbp_median + sbp_margin,
        "sbp_lower": sbp_median - sbp_margin,
        "margin": sbp_margin,
        "is_personalized": is_personalized,
        "records_needed": records_needed
    }

    # 5. 构造标准输出结构
    # 供 language.py 使用
    windows = {
        "general": {
            "baseline": {"start": baseline_recs[0].get("datetime"), "end": baseline_recs[-1].get("datetime"), "profile": base_profile, "stability": 1.0},
            "recent": {"start": recent_recs[0].get("datetime"), "end": recent_recs[-1].get("datetime"), "profile": recent_profile, "stability": 1.0}
        }
    }
    
    # 供 emergency.py 和 timeline.py 使用的分段
    segments = [{
        "start": sorted_records[0].get("datetime"),
        "end": sorted_records[-1].get("datetime"),
        "count": n,
        "type": "global",
        "profile": global_profile,
        "stability": 0.8 # 暂定固定值
    }]

    # 聚合症状到 events_by_segment (供 risk_level 使用)
    all_symptoms = []
    for r in recent_recs:
        syms = r.get("symptoms", []) or r.get("events", [])
        if isinstance(syms, list):
            all_symptoms.extend(syms)
    # 去重
    unique_symptoms = list(set(all_symptoms))
    events_by_segment = [unique_symptoms] if unique_symptoms else []

    return {
        "segments": segments,
        "events_by_segment": events_by_segment, 
        "trajectory": trajectory,
        "windows": windows,
        
        # ⭐ 核心修复：添加 risk_level.py 依赖的字段
        "base": {
            "sbp": base_profile.get("sbp", {}).get("median", 120),
            "dbp": base_profile.get("dbp", {}).get("median", 80),
            "pp": base_profile.get("pp", {}).get("median", 40),
            # 输出个体化带宽
            "band": band
        },
        "trend": trend_simple
    }