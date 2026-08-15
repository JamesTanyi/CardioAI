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
import time
import uuid
import glob

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

def _cleanup_old_files(output_dir, pattern, max_age_days=30):
    """
    ★ 新增：文件名从固定改成带时间戳的唯一名字之后，static/reports目录
    会持续累积图片文件，不会再像以前那样被同名覆盖。这里做一个简单的
    随手清理——每次生成新图时，顺手把同类型超过max_age_days天的旧文件
    删掉，不需要单独部署一个定时任务。清理失败不影响本次图表生成本身。
    """
    try:
        now = time.time()
        for filepath in glob.glob(os.path.join(output_dir, pattern)):
            if now - os.path.getmtime(filepath) > max_age_days * 86400:
                os.remove(filepath)
    except Exception as e:
        print(f"⚠️ 清理旧图表文件失败(不影响本次生成): {e}", flush=True)


def _arrow(value):
    if value >= 0.6:
        return "↑"
    elif value >= 0.3:
        return "→"
    else:
        return "↓"


# ★ 新增：Path A内部tier(低/关注/中)映射成0-1的分数，供图表柱状高度用。
# risk_level.py重构后不再有chronic_tension/acute_push这两个连续分数，
# 图表改用tier位置代替。
TIER_SCORE_MAP = {"低": 0.2, "关注": 0.6, "中": 0.95}


# ==========================
# 主函数：生成风险评分图
# ==========================

def plot_risk_scores(risk_bundle, output_dir):
    """
    ★ 改：risk_level.py重构后，risk_bundle不再有chronic_tension/acute_push
    这两个字段(旧的两个连续分数比大小的判断方式已经被Path A/B两条路径取代)，
    这里改用新schema：
        path                Path A 或 Path B
        tier                Path A内部低/关注/中(Path B时为None)
        path_b_triggers     Path B命中了哪几条(Path A时为空列表)
        acute_risk_level    兼容旧枚举值(low/moderate/moderate_high/critical)
        plaque_risk.score   独立维度，不受这次重构影响，继续可用

    输出：
        图像文件路径
    """
    path = risk_bundle.get("path", "A")
    tier = risk_bundle.get("tier")
    level = risk_bundle.get("acute_risk_level", "low")
    plaque_score = risk_bundle.get("plaque_risk", {}).get("score", 0.0)

    if path == "B":
        deviation_score = 1.0
        triggers = risk_bundle.get("path_b_triggers", [])
        tier_label = "Path B · " + "、".join(triggers) if triggers else "Path B"
    else:
        deviation_score = TIER_SCORE_MAP.get(tier, 0.2)
        tier_label = f"Path A · {tier or '低'}"

    color = RISK_COLOR.get(level, "#9E9E9E")  # 未知等级兜底为灰色，不再直接 KeyError 崩溃

    fig, ax = plt.subplots(figsize=(6, 4))

    # 两个柱状图：偏离/紧急程度(Path A按tier映射，Path B直接拉满) + 斑块压力风险(独立维度不变)
    ax.bar(["偏离/紧急程度", "斑块压力风险"], [deviation_score, plaque_score], color=[color, color], alpha=0.8)

    # 添加数值 + 箭头
    ax.text(0, deviation_score + 0.03, f"{deviation_score:.2f} {_arrow(deviation_score)}", ha="center", fontsize=12)
    ax.text(1, plaque_score + 0.03, f"{plaque_score:.2f} {_arrow(plaque_score)}", ha="center", fontsize=12)

    # 标题
    ax.set_title(f"{tier_label} · 综合等级：{level}", fontsize=14, color=color)
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("风险评分（0–1）")

    # 保存
    # ★ 修复：之前这里文件名固定是"risk_scores.png"——所有患者、每一次
    # 分析都写同一个文件，互相覆盖。这不只是"并发撞车"的问题：图表URL是
    # 提交测量时生成并存进那条历史记录里的，之后回看这条历史报告，理论上
    # 该显示"当时那次分析"对应的图，但因为文件名固定，回看的永远是当前
    # 全应用范围内最新生成的那张图，跟这条记录本身完全无关，医疗类应用
    # 这是不能接受的。改成时间戳+随机后缀的唯一文件名，每次分析各自独立。
    os.makedirs(output_dir, exist_ok=True)
    _cleanup_old_files(output_dir, "risk_scores_*.png")
    unique_suffix = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    out_path = os.path.join(output_dir, f"risk_scores_{unique_suffix}.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()

    return out_path