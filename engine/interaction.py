# app/engine/interaction.py

from typing import Dict, Any

METRICS = ["sbp", "dbp", "pp", "hr"]


def classify_metric_role(delta: float, status: str) -> str:
    """
    将单指标变化映射为“角色”：
    - anchor（锚点：稳定）
    - baseline_shift（托底变化）
    - wave_amplitude（波动幅度变化）
    - load_driver（负荷驱动）
    - calming（节律平静）
    - tension（节律紧张）
    """
    if status == "stable":
        return "anchor"

    if status == "down":
        if delta < -3:
            return "baseline_shift"
        return "calming"

    if status == "up":
        if delta > 3:
            return "load_driver"
        return "wave_amplitude"

    return "anchor"


def analyze_interaction(steady_result: Dict[str, Any], shift_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成指标互动关系解释：
    - 每个指标的角色
    - 系统整体状态（用力 / 回落 / 重新平衡 / 不稳定）
    """
    trajectory = steady_result.get("trajectory", {})
    details = shift_result.get("details", {})

    roles = {}
    for m in METRICS:
        steps = trajectory.get(m, [])
        if not steps:
            continue
        last = steps[-1]
        role = classify_metric_role(last["delta"], last["status"])
        roles[m] = role

    # 系统层面解释
    system_state = "stable"

    if "load_driver" in roles.values():
        system_state = "high_dynamic_load"
    elif "baseline_shift" in roles.values():
        system_state = "rebalancing"
    elif list(roles.values()).count("anchor") >= 3:
        system_state = "stable"
    else:
        system_state = "mild_adjustment"

    return {
        "roles": roles,
        "system_state": system_state,
    }

def parse_symptoms_from_text(text: str):
    """
    将语音识别文本解析为结构化症状列表。
    支持模糊匹配、多症状识别。
    """
    if not text:
        return []

    text = text.lower()
    detected = []

    for keyword, symptom in SYMPTOM_KEYWORDS.items():
        if keyword in text:
            detected.append(symptom)

    # 去重
    return list(set(detected))
