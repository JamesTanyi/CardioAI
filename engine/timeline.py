# app/engine/timeline.py
"""
事件时间轴（Event Timeline）
整合：
- 血压记录
- 稳态段切换
- 动力学事件（emergency）
- 症状事件（symptoms）
- 风险等级（risk_bundle）
"""

from typing import List, Dict
from datetime import datetime


# ==========================
# 1. 血压事件
# ==========================

def _bp_events(records: List[Dict]):
    events = []
    for r in records:
        # 核心修复：如果记录中没有血压数据，直接跳过，防止 KeyError: 'pp' 或 'sbp'
        if "sbp" not in r or "dbp" not in r:
            continue
            
        # 安全获取 pp
        pp = r.get("pp", r["sbp"] - r["dbp"])
        
        events.append({
            "time": r["datetime"],
            "type": "bp",
            "sbp": r["sbp"],
            "dbp": r["dbp"],
            "pp": pp,
            "hr": r.get("hr", 0),
            "desc": f"血压记录：{r['sbp']}/{r['dbp']} mmHg，PP={pp}"
        })
    return events


# ==========================
# 2. 稳态段切换事件
# ==========================

def _steady_state_events(steady_result):
    events = []
    for i, seg in enumerate(steady_result.get("segments", [])):
        events.append({
            "time": seg["start"],
            "type": "steady_start",
            "segment": i + 1,
            "desc": f"进入稳态段 {i+1}（稳定性={seg['stability']:.2f}）"
        })
    return events


# ==========================
# 3. 动力学事件（来自 emergency.py）
# ==========================

def _emergency_events(emergency_result, records):
    events = []
    latest = records[-1]

    if emergency_result["emergency"]:
        events.append({
            "time": latest["datetime"],
            "type": "acute_event",
            "desc": "检测到急性动力学事件（短期血压变化显著）",
            "details": emergency_result
        })

    return events


# ==========================
# 4. 症状事件（来自 symptoms.py）
# ==========================

def _symptom_events(events_by_segment, records):
    events = []
    if not events_by_segment:
        return events

    latest = records[-1]
    symptoms_container = events_by_segment[-1]

    # 兼容 list (稳态分析输出) 和 dict (旧版结构)
    if isinstance(symptoms_container, list):
        symptom_list = symptoms_container
    elif isinstance(symptoms_container, dict):
        symptom_list = list(symptoms_container.keys())
    else:
        symptom_list = []

    if symptom_list:
        events.append({
            "time": latest["datetime"],
            "type": "symptom",
            "symptoms": symptom_list,
            "desc": "出现症状：" + "、".join(symptom_list)
        })

    return events


# ==========================
# 5. 风险等级事件（来自 risk_bundle）
# ==========================

def _risk_events(risk_bundle, records):
    latest = records[-1]
    return [{
        "time": latest["datetime"],
        "type": "risk",
        "risk_level": risk_bundle["acute_risk_level"],
        "desc": f"急性风险等级：{risk_bundle['acute_risk_level']}"
    }]


# ==========================
# 6. 主入口：生成时间轴
# ==========================

def build_timeline(records, steady_result, emergency_result, events_by_segment, risk_bundle):
    timeline = []

    timeline += _bp_events(records)
    timeline += _steady_state_events(steady_result)
    timeline += _emergency_events(emergency_result, records)
    timeline += _symptom_events(events_by_segment, records)
    timeline += _risk_events(risk_bundle, records)

    # 按时间排序
    timeline.sort(key=lambda x: x["time"])

    return timeline
