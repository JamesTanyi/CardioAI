# engine/language.py
"""
三角色语言生成模块

角色定位：
  user    患者本人 — 客观呈现个人稳态与变化，鼓励持续测量，行动提示简明
  watcher 关注者   — 泛化"家属"，可以是子女/朋友/社区医护，聚焦波动信号和督促行动
  doctor  医生     — 纯结构化数据+时间序列，判断由医生做，系统不解释不建议

★ 本次重写核心变化：
  不再给患者/家属任何"低/关注/中"这类程度标签——只讲事实(数值+这段
  时间的最高最低值+跟个人稳态带的差异)+趋势方向(14d vs 28d滚动对比，
  不是绝对高低数字)+行动建议(关注/重视/建议就医)。风险判定内部走的是
  Path A(渐进式分档)/Path B(优先特例，命中即直接判定需要就医)两条路径
  ——具体见risk_level.py，这里只负责把判断结果转成合适的措辞，
  不重新做判断。Path B触发时统一明确建议立即就医，并提示就医时可以
  把医生端报告页面出示给接诊医生参考。医生端继续看完整原始数据，
  程度分档、触发依据、既往病史都完整展示，结论由医生自己下。

订阅留存设计：
  user    — 进度感（还差X次解锁）、稳态带专属感、连续打卡奖励
  watcher — 远程安心感、具体可执行的督促动作
  doctor  — 数据完整性本身就是价值，不加废话
"""

from datetime import datetime
from typing import List, Dict, Any

from engine.lifecycle import (
    PHASE_1_ONBOARDING,
    PHASE_2_BASELINE,
    PHASE_3_HABIT,
    PHASE_4_IMPROVE,
    PHASE_5_MASTERY,
    PHASE_6_MAINTENANCE
)

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

METRIC_LABELS = {"sbp": "收缩压", "dbp": "舒张压", "hr": "心率", "pp": "脉压差"}


def _fmt(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt) if dt else "N/A"


def _delta_word(delta: float, unit: str = "mmHg") -> str:
    """将数值偏差转成自然语言"""
    if abs(delta) < 2:
        return "基本持平"
    direction = "升高" if delta > 0 else "下降"
    magnitude = "轻度" if abs(delta) < 6 else "明显"
    return f"{magnitude}{direction} {abs(delta):.0f}{unit}"


def _metric_label(m: str) -> str:
    return METRIC_LABELS.get(m, m.upper())


def _get_window(steady_result: Dict) -> Dict:
    """智能回退：优先取最大可用窗口(按点数的窗口，供医生端结构化数据用)"""
    windows = steady_result.get("windows", {})
    for k in ["30pt", "20pt", "10pt", "5pt", "3pt"]:
        if k in windows:
            return windows[k], k
    return {}, "N/A"


def _trend_lines(steady_result: Dict) -> List[str]:
    """提取各指标趋势(按点数窗口)，供医生端结构化数据用"""
    trajectory = steady_result.get("trajectory", {})
    if not trajectory:
        return []
    _, win_label = _get_window(steady_result)
    lines = []
    for m in ["sbp", "dbp", "pp", "hr"]:
        steps = trajectory.get(m, [])
        step = next((s for s in steps if s["window"] == win_label), None)
        if step:
            lines.append(f"{m.upper()}: {_delta_word(step['delta'])}")
    return lines


def _fact_and_trend_lines(steady_result: Dict, metrics=("sbp", "dbp")) -> List[str]:
    """
    ★ 新增：只讲事实，给患者/家属看的客观描述——用14d/28d动态趋势窗口
    (不是绝对高低数字判断)+这段时间的最高最低值+跟个人稳态带的差异。
    不产出任何"低/关注/中"这类程度判断，那是Path A分档的事，分档结果
    只用来选后面的行动建议措辞，不会出现在这段事实描述里。
    """
    dynamic_trend = steady_result.get("dynamic_trend", {}) or {}
    bands = steady_result.get("bands", {}) or {}
    lines = []
    for m in metrics:
        dt = dynamic_trend.get(m)
        if not dt:
            continue
        band = bands.get(m)
        label = _metric_label(m)
        delta_word = _delta_word(dt["delta"])
        lines.append(f"{label}：最近14天中位数 {dt['recent_median']:.0f}，比再往前14天{delta_word}")
        if band:
            max_over = dt["recent_max"] - band["upper"]
            min_under = band["lower"] - dt["recent_min"]
            if max_over > 0:
                lines.append(f"　这段时间最高一次 {dt['recent_max']:.0f}，超出您平时的稳定范围约 {max_over:.0f}")
            if min_under > 0:
                lines.append(f"　这段时间最低一次 {dt['recent_min']:.0f}，低于您平时的稳定范围约 {min_under:.0f}")
    return lines


def _action_advice(risk_bundle: Dict, for_role: str = "user") -> List[str]:
    """
    ★ 新增：行动建议——不出现"低/关注/中"这类程度标签，只用"关注/重视/
    建议就医"这类行动词。Path B命中时统一是"立即就医"，并提示就医时
    可以把医生端报告页面出示给接诊医生参考；有高危病史时额外提醒一句。
    Path A按tier选择对应措辞。for_role区分患者本人("您")和家属("TA")视角。
    """
    you_or_ta = "您" if for_role == "user" else "TA"

    if risk_bundle.get("path") == "B":
        lines = [f"**建议{you_or_ta}立即就医。**"]
        if risk_bundle.get("has_high_risk_history"):
            lines.append(f"结合{you_or_ta}此前的病史，这次的情况需要更谨慎对待，不要拖延。")
        lines.append("就医时，建议带上或出示医生端报告页面，方便接诊医生快速了解情况。")
        return lines

    tier = risk_bundle.get("tier", "低")
    if tier == "中":
        return [f"建议重视，尽快找时间带{you_or_ta}看一下医生，把这段时间的记录一起带上。"]
    elif tier == "关注":
        return [f"建议关注，按平时节奏继续记录，留意接下来几天的变化。"]
    else:
        return [f"目前在{you_or_ta}平时的稳定范围内，继续保持。"]


def _vascular_pp(steady_result: Dict) -> Dict:
    """脉压差分析(按点数窗口，供医生端/次要展示用)"""
    win, _ = _get_window(steady_result)
    if not win:
        return {}
    base = win.get("baseline", {}).get("profile", {})
    recent = win.get("recent", {}).get("profile", {})
    if "pp" not in recent or "pp" not in base:
        return {}
    pp_val = recent["pp"]["median"]
    pp_delta = pp_val - base["pp"]["median"]
    return {"value": pp_val, "delta": pp_delta}


# ──────────────────────────────────────────────
# USER — 患者本人
# 原则：客观、不恐慌、进度感、行动提示简明，不下程度结论
# ──────────────────────────────────────────────

def _generate_user_text(records: List[Dict], steady_result: Dict, risk_bundle: Dict) -> str:
    long_data = risk_bundle.get("longitudinal", {})
    ux_phase = long_data.get("ux_phase", PHASE_1_ONBOARDING)
    total_days = long_data.get("total_days", 0)
    streak = long_data.get("current_streak", 1)
    path = risk_bundle.get("path", "A")
    base_info = steady_result.get("base", {}).get("band", {})
    needed = base_info.get("records_needed", 0)

    lines = []

    # ── Path B 优先：命中任意特例触发条件，直接明确建议就医 ──
    if path == "B":
        lines.append("⚠️ 这次的测量结果需要您特别留意。")
        lines.append("")

        latest = records[-1] if records else {}
        sbp = latest.get("sbp")
        dbp = latest.get("dbp")
        if sbp is not None and dbp is not None:
            lines.append(f"**本次血压 {sbp:.0f}/{dbp:.0f} mmHg。**")
        lines.append("")

        symptom_lvl = risk_bundle.get("symptom_level", "none")
        if symptom_lvl in ("high", "medium"):
            lines.append("您提到了身体不适，建议先静坐休息。")
        else:
            lines.append("如果现在有头晕、胸闷、手脚无力等感觉，请立即静坐休息并告知家人。")
        lines.append("")

        for line in _action_advice(risk_bundle, for_role="user"):
            lines.append(line)
        lines.append("")
        lines.append("继续保持测量记录，能帮助医生更准确地判断情况。")
        return "\n".join(lines)

    # ── 阶段1：入门期（1-3天）──
    if ux_phase == PHASE_1_ONBOARDING:
        lines.append("👋 您好，感谢开始记录您的血压健康档案。")
        lines.append("")
        if needed > 0:
            lines.append(f"📊 个人稳态模型建立中，还需 {needed} 次测量即可解锁专属分析。")
        lines.append("")
        lines.append("💡 建议每天同一时间测量，帮助系统了解您的身体节律。")
        lines.append("数据越连续，分析越准确，对您的保护也越有针对性。")

    # ── 阶段2：基线确认期（4-14天）──
    elif ux_phase == PHASE_2_BASELINE:
        lines.append(f"📋 已记录 {total_days} 天，您的个人基线正在确认中。")
        lines.append("")
        trend = _trend_lines(steady_result)
        if trend:
            lines.append("近期变化：")
            for t in trend:
                lines.append(f"  {t}")
            lines.append("")
        for line in _action_advice(risk_bundle, for_role="user"):
            lines.append(line)
        lines.append("")
        lines.append(f"🔥 已连续记录 {streak} 天，继续保持有助于建立更精准的个人模型。")

    # ── 阶段3：习惯养成期（15-30天）──
    elif ux_phase == PHASE_3_HABIT:
        lines.append(f"🌱 已坚持 {total_days} 天，连续打卡 {streak} 天。")
        lines.append("")
        fact_lines = _fact_and_trend_lines(steady_result)
        if fact_lines:
            lines.append("您的近期血压情况：")
            for f in fact_lines:
                lines.append(f"  {f}")
            lines.append("")

        for line in _action_advice(risk_bundle, for_role="user"):
            lines.append(line)

    # ── 阶段4-6：成熟期（31天以上）──
    else:
        lines.append(f"📈 健康档案第 {total_days} 天 · 连续 {streak} 天")
        lines.append("")

        fact_lines = _fact_and_trend_lines(steady_result)
        if fact_lines:
            lines.append("您的近期血压情况：")
            for f in fact_lines:
                lines.append(f"  {f}")
            lines.append("")

        for line in _action_advice(risk_bundle, for_role="user"):
            lines.append(line)

        # 脉压差(次要参考，非结论)
        pp = _vascular_pp(steady_result)
        if pp:
            delta_word = _delta_word(pp["delta"])
            lines.append("")
            lines.append(f"血管弹性参考（脉压差）：{pp['value']:.0f} mmHg，较基线{delta_word}。")

    # ── 留存钩子 ──
    lines.append("")
    lines.append("─" * 20)
    if needed > 0:
        lines.append(f"再测 {needed} 次，解锁您的专属稳态带分析 →")
    else:
        lines.append("持续记录让系统对您了解更深，保护更精准。")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# WATCHER — 关注者（泛化家属）
# 原则：波动信号明确、督促行动具体可执行、远程安心，不下程度结论
# ──────────────────────────────────────────────

def _generate_watcher_text(steady_result: Dict, risk_bundle: Dict) -> str:
    long_data = risk_bundle.get("longitudinal", {})
    streak = long_data.get("current_streak", 0)
    continuity = long_data.get("continuity_score", 1.0)
    path = risk_bundle.get("path", "A")
    tier = risk_bundle.get("tier", "低")
    symptom_lvl = risk_bundle.get("symptom_level", "none")
    ux_phase = long_data.get("ux_phase", PHASE_1_ONBOARDING)
    total_days = long_data.get("total_days", 0)

    lines = []

    # ── 状态信号：只讲事实+建议，不出现程度标签 ──
    if path == "B":
        lines.append("🚨 需要您立即关注")
        lines.append("TA这次的测量结果需要特别留意，建议您现在联系确认状态。")
        if symptom_lvl in ("high", "medium"):
            lines.append("同时伴有身体不适症状，建议直接前往就医，不要等待。")
        else:
            lines.append("目前无明显不适症状，但建议今天陪同或电话确认用药情况。")
        for line in _action_advice(risk_bundle, for_role="watcher"):
            lines.append(line)
    else:
        fact_lines = _fact_and_trend_lines(steady_result)
        if tier == "中":
            lines.append("⚠️ 需要留意")
        elif tier == "关注":
            lines.append("👀 有些起伏")
        else:
            lines.append("✅ 目前平稳")
            lines.append(f"TA已坚持记录 {total_days} 天，血压状态稳定，您可以放心。")

        if fact_lines:
            lines.append("TA近期的血压情况：")
            for f in fact_lines:
                lines.append(f"  {f}")

        if tier in ("中", "关注"):
            for line in _action_advice(risk_bundle, for_role="watcher"):
                lines.append(line)

    lines.append("")

    # ── 测量依从性督促 ──
    lines.append("📋 测量情况")
    if streak >= 7:
        lines.append(f"TA已连续测量 {streak} 天，非常自律！建议您发消息鼓励一下。")
    elif streak >= 3:
        lines.append(f"TA已连续测量 {streak} 天，保持得不错。")
    elif continuity < 0.6:
        lines.append("⚠️ 最近测量不太规律，建议您提醒TA每天固定时间测量。")
        lines.append("连续的数据对分析准确性非常关键，断档会影响风险判断。")
    else:
        lines.append("测量频率正常，请协助TA继续保持。")

    lines.append("")

    # ── 具体督促行动 ──
    lines.append("🛡️ 您现在可以做什么")

    if path == "B":
        lines.append("① 现在联系TA，询问是否有头晕、胸闷、手脚无力等感觉")
        if symptom_lvl in ("high", "medium"):
            lines.append("② 有不适症状 → 建议直接就医或拨打急救")
        else:
            lines.append("② 无不适 → 提醒TA静坐休息，今天避免剧烈活动")
        lines.append("③ 检查TA最近是否按时服药，有无漏服")
        lines.append("④ 建议今明两天各多测一次，观察变化")

    elif tier == "中":
        lines.append("① 问问TA最近睡眠和情绪状态")
        lines.append("② 提醒按时服药，饮食清淡，少盐")
        lines.append("③ 建议明天早晚各测一次")
        lines.append("④ 如连续两天仍然偏离明显，建议陪同门诊复查")

    elif tier == "关注":
        lines.append("① 提醒TA今天注意休息，保证睡眠")
        lines.append("② 确认今天是否按时服药")
        lines.append("③ 继续观察明天的测量数据")

    else:
        lines.append("① 目前不需要额外干预")
        if streak > 0:
            lines.append(f"② 可以发消息夸夸TA坚持了 {streak} 天，鼓励很重要")
        lines.append("③ 继续关注每天的测量提醒")

    lines.append("")

    # ── 趋势简报（仅成熟期显示，按点数窗口，供次要参考）──
    if ux_phase not in (PHASE_1_ONBOARDING, PHASE_2_BASELINE):
        trend = _trend_lines(steady_result)
        if trend:
            lines.append("📊 近期变化趋势（与TA个人基线比较）")
            for t in trend:
                lines.append(f"  {t}")
            lines.append("")

        pp = _vascular_pp(steady_result)
        if pp and abs(pp["delta"]) >= 3:
            lines.append(f"血管弹性参考（脉压差）：{pp['value']:.0f} mmHg，{_delta_word(pp['delta'])}")
            lines.append("")

    # ── 留存钩子 ──
    lines.append("─" * 20)
    lines.append("TA的每一次测量都在积累健康数据。")
    lines.append("您的关注和提醒，是让TA坚持下去的最大动力。")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# DOCTOR — 医生
# 原则：纯数据+时间序列，无解释，无建议，判断由医生做
# ──────────────────────────────────────────────

def _generate_doctor_text(
    records: List[Dict],
    steady_result: Dict,
    risk_bundle: Dict,
    figure_paths: Dict
) -> str:
    lines = []

    # ── 时间序列概览 ──
    lines.append("## Time Series")
    if records:
        t0 = records[0].get("datetime") or records[0].get("timestamp")
        t1 = records[-1].get("datetime") or records[-1].get("timestamp")
        lines.append(f"- Start : {_fmt(t0)}")
        lines.append(f"- End   : {_fmt(t1)}")
        lines.append(f"- N     : {len(records)}")
    else:
        lines.append("- No records")
    lines.append("")

    # ── 稳态窗口数据(按点数) ──
    win, win_label = _get_window(steady_result)
    lines.append(f"## Steady-State Window ({win_label})")
    if win:
        base = win.get("baseline", {})
        recent = win.get("recent", {})
        if base and recent:
            lines.append(f"- Baseline : {_fmt(base.get('start'))} → {_fmt(base.get('end'))}  stability={base.get('stability', 0):.3f}")
            lines.append(f"- Recent   : {_fmt(recent.get('start'))} → {_fmt(recent.get('end'))}  stability={recent.get('stability', 0):.3f}")
            lines.append("- Baseline profile (median):")
            for m, v in base.get("profile", {}).items():
                lines.append(f"    {m.upper():4s}: {v.get('median', 0):.1f}  IQR={v.get('iqr', 0):.1f}")
            lines.append("- Recent profile (median):")
            for m, v in recent.get("profile", {}).items():
                lines.append(f"    {m.upper():4s}: {v.get('median', 0):.1f}  IQR={v.get('iqr', 0):.1f}")
        else:
            lines.append("- Insufficient data for baseline comparison")
    else:
        lines.append("- No window data")
    lines.append("")

    # ── ★ 新增：多指标非对称band + 当前偏离比例(Path A分档的原始依据) ──
    lines.append("## Personalized Bands (SBP/DBP/HR/PP)")
    bands = steady_result.get("bands", {}) or {}
    current_deviation = steady_result.get("current_deviation", {}) or {}
    for m in ["sbp", "dbp", "hr", "pp"]:
        band = bands.get(m)
        if not band:
            continue
        dev = current_deviation.get(m, 0)
        lines.append(
            f"- {m.upper():4s}: median={band['median']:.1f}  "
            f"range=[{band['lower']:.1f}, {band['upper']:.1f}]  "
            f"current_deviation_ratio={dev:.2f}"
        )
    lines.append("")

    # ── ★ 新增：14d/28d动态趋势(原始数据，跟患者/家属端用的是同一份) ──
    lines.append("## 14d / 28d Dynamic Trend")
    dynamic_trend = steady_result.get("dynamic_trend", {}) or {}
    if dynamic_trend:
        for m, dt in dynamic_trend.items():
            lines.append(
                f"- {m.upper():4s}: recent14d_median={dt['recent_median']:.1f}  "
                f"prior14d_median={dt['prior_median']:.1f}  delta={dt['delta']:.1f}  "
                f"recent14d_max={dt['recent_max']:.1f}  recent14d_min={dt['recent_min']:.1f}"
            )
    else:
        lines.append("- Insufficient calendar-day data")
    lines.append("")

    # ── 稳态分段(置信度融合确认后的真实结构变化) ──
    lines.append("## Confirmed Segments (confidence-fused change-point detection)")
    segments = steady_result.get("segments", [])
    if segments:
        for i, seg in enumerate(segments):
            lines.append(f"### Seg {i+1} [{seg.get('type','?').upper()}]")
            lines.append(f"  {_fmt(seg.get('start'))} → {_fmt(seg.get('end'))}  N={seg.get('count',0)}  stability={seg.get('stability',0):.3f}")
            for m, v in seg.get("profile", {}).items():
                lines.append(f"  {m.upper():4s}: {v.get('median',0):.1f}  IQR={v.get('iqr',0):.1f}")
    else:
        lines.append("- No segments")
    lines.append("")

    # ── ★ 改：风险评分——反映Path A/B新架构，不再是旧的chronic_tension/
    #    acute_push两个分数 ──
    lines.append("## Risk Assessment (Path A/B)")
    path = risk_bundle.get("path", "A")
    lines.append(f"- path              : {path}")
    if path == "A":
        lines.append(f"- tier              : {risk_bundle.get('tier', 'N/A')}")
    else:
        lines.append(f"- path_b_triggers   : {risk_bundle.get('path_b_triggers', [])}")
    lines.append(f"- acute_risk_level  : {risk_bundle.get('acute_risk_level', 'N/A')}  (legacy flat enum, for backward compat)")
    lines.append(f"- symptom_level     : {risk_bundle.get('symptom_level', 'N/A')}")
    lines.append(f"- has_high_risk_history : {risk_bundle.get('has_high_risk_history', False)}")
    plaque = risk_bundle.get("plaque_risk", {})
    lines.append(f"- plaque_risk       : {plaque.get('level','N/A')}  score={plaque.get('score',0):.3f}  reasons={plaque.get('reasons',[])}")
    lines.append("")

    # ── 纵向依从性 ──
    long_data = risk_bundle.get("longitudinal", {})
    lines.append("## Longitudinal Adherence")
    lines.append(f"- stage           : {long_data.get('stage','N/A')}")
    lines.append(f"- ux_phase        : {long_data.get('ux_phase','N/A')}")
    lines.append(f"- maturity        : {long_data.get('maturity_level','N/A')}")
    lines.append(f"- active_days     : {long_data.get('days_active',0)}")
    lines.append(f"- total_days      : {long_data.get('total_days',0)}")
    lines.append(f"- current_streak  : {long_data.get('current_streak',0)}")
    lines.append(f"- continuity      : {long_data.get('continuity_score',0):.3f}")
    lines.append("")

    # ── 模式识别 ──
    patterns = figure_paths.get("patterns", {})
    lines.append("## Patterns")
    lines.append(f"- nocturnal_dip   : {patterns.get('nocturnal_dip','N/A')}")
    lines.append(f"- morning_surge   : {patterns.get('morning_surge','N/A')}")
    lines.append(f"- variability     : {patterns.get('variability','N/A')}")
    lines.append("")

    # ── 轨迹数据(按点数窗口) ──
    lines.append("## Trajectory")
    trajectory = steady_result.get("trajectory", {})
    for m, steps in trajectory.items():
        for step in steps:
            lines.append(f"  {m.upper()} [{step.get('window','?')}] delta={step.get('delta',0):.1f}")
    lines.append("")

    # ── 图表链接 ──
    chart_fields = ["risk_scores_url", "symptom_timeline_url"]
    has_charts = any(figure_paths.get(f) for f in chart_fields)
    if has_charts:
        lines.append("## Charts")
        for f in chart_fields:
            url = figure_paths.get(f)
            if url:
                label = f.replace("_url", "").replace("_", " ").title()
                lines.append(f"### {label}")
                lines.append(f'<img src="{url}" style="width:100%;max-width:640px;border-radius:6px;border:1px solid #ddd;margin:8px 0;">')
        lines.append("")

    lines.append("---")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  N={len(records)}")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def generate_language_blocks(
    records: List[Dict],
    steady_result: Dict,
    risk_bundle: Dict,
    figure_paths: Dict
) -> Dict[str, str]:
    return {
        "user":    _generate_user_text(records, steady_result, risk_bundle),
        "watcher": _generate_watcher_text(steady_result, risk_bundle),
        "doctor":  _generate_doctor_text(records, steady_result, risk_bundle, figure_paths),
        # 向后兼容：保留 family 字段指向 watcher
        "family":  _generate_watcher_text(steady_result, risk_bundle),
    }