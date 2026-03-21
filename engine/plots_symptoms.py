# app/engine/plots_symptoms.py
"""
症状时间序列图（Symptom Timeline Plot）
- 高危症状：红色
- 中危症状：橙色
- 低危症状：黄色
"""

import matplotlib.pyplot as plt
import os
from datetime import datetime


# ==========================
# 症状分级颜色
# ==========================

SYMPTOM_COLORS = {
    "high": "#F44336",      # 红色
    "medium": "#FF9800",    # 橙色
    "low": "#FFC107",       # 黄色
}


# ==========================
# 症状分级规则（与 risk_level 保持一致）
# ==========================

HIGH_RISK_SYMPTOMS = {
    "chest_pain",
    "weakness_one_side",
    "slurred_speech",
    "vision_loss",
    "confusion",
    "thunderclap_headache",
}

MEDIUM_RISK_SYMPTOMS = {
    "chest_tightness",
    "dizzy",
    "palpitations",
    "short_breath",
    "severe_headache",
}

LOW_RISK_SYMPTOMS = {
    "mild_headache",
    "fatigue",
    "general_discomfort",
    "anxiety",
}


def _symptom_level(sym):
    if sym in HIGH_RISK_SYMPTOMS:
        return "high"
    if sym in MEDIUM_RISK_SYMPTOMS:
        return "medium"
    if sym in LOW_RISK_SYMPTOMS:
        return "low"
    return None


# ==========================
# 主函数：绘制症状时间序列图
# ==========================

def plot_symptom_timeline(records, events_by_segment, output_dir):
    """
    输入：
        records: 血压记录（用于获取时间轴）
        events_by_segment: 症状结构（来自 symptoms_to_segments）

    输出：
        图像文件路径
    """

    # 如果没有症状，直接返回 None
    if not events_by_segment or not events_by_segment[-1]:
        return None

    symptoms_container = events_by_segment[-1]
    latest_time = records[-1]["datetime"]

    # 兼容 list 和 dict
    symptom_list = list(symptoms_container.keys()) if isinstance(symptoms_container, dict) else list(symptoms_container)

    # 准备绘图
    fig, ax = plt.subplots(figsize=(8, 2 + len(symptom_list) * 0.4))

    y_labels = []
    y_positions = []
    colors = []

    for i, sym in enumerate(symptom_list):
        level = _symptom_level(sym)
        if not level:
            continue

        y_labels.append(sym)
        y_positions.append(i)
        colors.append(SYMPTOM_COLORS[level])

        # 画条状图（症状发生在最新时间点）
        ax.barh(i, 1, left=latest_time.timestamp(), color=SYMPTOM_COLORS[level], alpha=0.8)

    # 设置 y 轴
    ax.set_yticks(y_positions)
    ax.set_yticklabels(y_labels)

    # 设置 x 轴为时间
    ax.set_xlabel("时间")
    ax.set_title("症状时间序列图（Symptom Timeline）")

    # 格式化 x 轴为时间
    ax.get_xaxis().set_visible(False)

    # 保存
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "symptom_timeline.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()

    return path
