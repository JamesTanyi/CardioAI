# app/engine/emergency.py
"""
新版 emergency.py
职责：从血压时间序列中提取“急性动力学信号”，供 risk_level.py 使用。
不做风险分层，不做语言解释。
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta


# ==========================
# 1. 找到参考记录（48 小时内）
# ==========================

def _find_reference_record(records: List[Dict], hours: int = 48):
    """
    找到距离最新记录 within hours 的参考记录
    """
    if len(records) < 2:
        return None

    latest = records[-1]
    for r in reversed(records[:-1]):
        dt_diff = (latest["datetime"] - r["datetime"]).total_seconds() / 3600
        if dt_diff <= hours:
            return r
        else:
            break
    return None


# ==========================
# 2. 计算短期变化（SBP/DBP/PP）
# ==========================

def _compute_short_term_changes(records: List[Dict], hours: int = 48):
    """
    返回 SBP/DBP/PP 在 hours 小时内的变化量
    """
    ref = _find_reference_record(records, hours)
    if not ref:
        return {"dsbp": 0, "ddbp": 0, "dpp": 0}

    latest = records[-1]

    # 使用 get 方法安全获取，如果 pp 不存在则尝试现场计算，或使用默认值防止崩溃
    dsbp = latest.get("sbp", 120) - ref.get("sbp", 120)
    ddbp = latest.get("dbp", 80) - ref.get("dbp", 80)
    
    latest_pp = latest.get("pp", latest.get("sbp", 120) - latest.get("dbp", 80))
    ref_pp = ref.get("pp", ref.get("sbp", 120) - ref.get("dbp", 80))
    dpp = latest_pp - ref_pp

    return {
        "dsbp": dsbp,
        "ddbp": ddbp,
        "dpp": dpp,
    }


# ==========================
# 3. 多指标同步变化
# ==========================

def _detect_synchronous_shift(changes: Dict[str, float]):
    """
    判断是否存在多指标同步变化（≥2 个指标显著变化）
    """
    flags = [
        abs(changes["dsbp"]) >= 20,
        abs(changes["ddbp"]) >= 15,
        abs(changes["dpp"]) >= 15,
    ]
    return sum(flags) >= 2


# ==========================
# 4. 稳态失稳（结构性稳定性下降）
# ==========================

def _detect_instability(steady_result: Dict[str, Any]):
    """
    判断最近稳态段是否出现“稳定性下降”
    """
    segments = steady_result.get("segments", [])
    if len(segments) < 2:
        return False

    prev = segments[-2]["stability"]
    curr = segments[-1]["stability"]

    # 稳定性下降超过一定阈值
    return (prev - curr) > 0.15


# ==========================
# 5. 主入口：急性动力学信号
# ==========================

def analyze_emergency(records, steady_result) -> Dict[str, Any]:
    """
    输出急性动力学信号（供 risk_level.py 使用）
    不做风险分层。
    """

    # 1) 短期变化
    changes = _compute_short_term_changes(records, hours=48)

    # 2) 多指标同步变化
    sync = _detect_synchronous_shift(changes)

    # 3) 稳态失稳
    instability = _detect_instability(steady_result)

    # 4) 是否存在“急性动力学事件”
    emergency_flag = (
        abs(changes["dsbp"]) >= 20
        or abs(changes["ddbp"]) >= 15
        or abs(changes["dpp"]) >= 15
        or sync
        or instability
    )

    return {
        "short_term_changes": changes,       # {'dsbp': x, 'ddbp': y, 'dpp': z}
        "synchronous_shift": sync,           # True / False
        "instability": instability,          # True / False
        "emergency": emergency_flag,         # True / False（仅表示“存在急性动力学事件”）
    }
