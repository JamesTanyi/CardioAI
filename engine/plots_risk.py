# app/engine/plots_risk.py
"""
风险评分可视化（Risk Visualization）
生成：
- 慢性张力（chronic tension）
- 急性推力（acute push）
- 综合急性风险等级（颜色编码）
"""

import matplotlib.pyplot as plt
import matplotlib
import os

# 部署环境（容器/云托管）通常不带中文字体，不配置会导致图里中文全部变成方框。
# 按优先级尝试几个常见的中文字体，一个都找不到就退回默认。
for _font in ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei", "Microsoft YaHei", "PingFang SC"]:
    if _font in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
        matplotlib.rcParams["font.sans-serif"] = [_font]
        break
matplotlib.rcParams["axes.unicode_minus"] = False


# ==========================
# 颜色映射
# ==========================

RISK_COLOR = {
    "low": "#4CAF50",            # 绿色
    "moderate": "#FFC107",       # 黄色
    "moderate_high": "#FF9800",  # 橙色
    "high": "#F44336",           # 红色
    "critical": "#B71C1C",       # 深红色（risk_level.py 会产出这个等级，原字典缺失会导致 KeyError）
}


# ==========================
# 趋势箭头
# ==========================

def _arrow(value):
    if value >= 0.6:
        return "↑"
    elif value >= 0.3:
        return "→"
    else:
        return "↓"


# ==========================
# 主函数：生成风险评分图
# ==========================

def plot_risk_scores(risk_bundle, output_dir):
    """
    输入：
        risk_bundle = {
            "symptom_level": ...,
            "chronic_tension": float,
            "acute_push": float,
            "acute_risk_level": str
        }

    输出：
        图像文件路径
    """

    chronic = risk_bundle["chronic_tension"]
    acute = risk_bundle["acute_push"]
    level = risk_bundle["acute_risk_level"]

    color = RISK_COLOR.get(level, "#9E9E9E")  # 未知等级兜底为灰色，不再直接 KeyError 崩溃

    fig, ax = plt.subplots(figsize=(6, 4))

    # 两个柱状图
    ax.bar(["慢性张力", "急性推力"], [chronic, acute], color=[color, color], alpha=0.8)

    # 添加数值 + 箭头
    ax.text(0, chronic + 0.03, f"{chronic:.2f} {_arrow(chronic)}", ha="center", fontsize=12)
    ax.text(1, acute + 0.03, f"{acute:.2f} {_arrow(acute)}", ha="center", fontsize=12)

    # 标题
    ax.set_title(f"急性风险等级：{level}", fontsize=14, color=color)
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("风险评分（0–1）")

    # 保存
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "risk_scores.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()

    return path
