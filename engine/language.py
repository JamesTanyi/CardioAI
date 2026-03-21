# app/engine/language.py

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

# ==========================
# 工具函数
# ==========================

def _fmt(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def _describe_delta(delta):
    if abs(delta) < 2:
        return "几乎没有变化"
    elif abs(delta) < 5:
        return f"轻度{'升高' if delta > 0 else '下降'}（约 {abs(delta)} mmHg）"
    else:
        return f"明显{'升高' if delta > 0 else '下降'}（约 {abs(delta)} mmHg）"


def _explain_trend(steady_result):
    """【逻辑统一】解释 SBP/DBP/PP/HR 的长期趋势，使用 trajectory 结果"""
    trajectory = steady_result.get("trajectory", {})
    if not trajectory:
        return []

    lines = []
    
    # 使用最大可用窗口的轨迹结果，以反映最稳定的长期趋势
    target_win_label = None
    for k in ["30pt", "20pt", "10pt", "5pt", "3pt"]:
        if k in steady_result.get("windows", {}):
            target_win_label = k
            break

    if not target_win_label:
        return []

    for m in ["sbp", "dbp", "pp", "hr"]:
        metric_traj = trajectory.get(m, [])
        if not metric_traj:
            continue
        
        # 寻找目标窗口的分析步骤
        target_step = next((step for step in metric_traj if step["window"] == target_win_label), None)
        if target_step:
            lines.append(f"{m.upper()}：{_describe_delta(target_step['delta'])}")

    return lines


def _analyze_vascular_status(steady_result):
    """分析血管物理状态（基于脉压差 PP）"""
    windows = steady_result.get("windows", {})
    
    # 智能回退：优先找大窗口，没有则找小窗口
    target_win = None
    for k in ["30pt", "20pt", "10pt", "5pt", "3pt"]:
        if k in windows:
            target_win = windows[k]
            break
            
    if not target_win:
        return None

    base = target_win["baseline"]["profile"]
    recent = target_win["recent"]["profile"]
    
    if "pp" not in recent or "pp" not in base:
        return None

    pp_val = recent["pp"]["median"]
    pp_base = base["pp"]["median"]
    pp_delta = pp_val - pp_base
    
    # 1. 稳态解读 (General State) - 解释血管一般状态
    status_desc = ""
    if pp_val >= 60:
        status_desc = "脉压差偏大，提示血管壁弹性可能减弱，硬化风险增加。"
    elif pp_val <= 20:
        status_desc = "脉压差偏小，需关注心脏泵血功能或外周阻力变化。"
    else:
        status_desc = "脉压差处于正常区间，血管弹性维持在较好状态。"
        
    # 2. 变化解读 (Physical Changes) - 解释近期物理变化
    trend_desc = ""
    if pp_delta >= 5:
        trend_desc = "近期脉压差有增大趋势，血管承受的物理冲击力在增强。"
    elif pp_delta <= -5:
        trend_desc = "近期脉压差有所缩小，血管承受的物理冲击力在减弱。"
    else:
        trend_desc = "近期脉压差保持稳定，血管物理状态无明显波动。"
        
    return {
        "value": pp_val,
        "status": status_desc,
        "trend": trend_desc
    }

def _get_plaque_risk_suggestions(reasons: List[str]) -> List[str]:
    """根据斑块风险的成因，生成动态的临床建议"""
    suggestions = []
    if "high_pulse_pressure" in reasons:
        suggestions.append("高脉压差提示大动脉僵硬度增加，是心血管事件的独立预测因子。")
    if "high_bp_variability" in reasons:
        suggestions.append("高血压变异性增加剪切力波动，建议考虑24h-ABPM以评估变异性及夜间血压模式。")
    if "morning_surge" in reasons:
        suggestions.append("晨峰现象是斑块破裂的独立触发因素，建议评估降压药的给药时间（如考虑长效制剂或睡前给药）。")
    if "tachycardia_stress" in reasons:
        suggestions.append("心率过快增加斑块受冲击频率，需关注心率控制。")
    if not suggestions:
        suggestions.append("当前血流动力学状态可能增加斑块机械应力，建议关注颈动脉斑块稳定性。")
    return suggestions

# ==========================
# 风险表达规范 (Risk Expression Engine)
# ==========================

class RiskExpressionEngine:
    """
    风险表达规范引擎
    负责将数值化的风险评分转换为标准化的自然语言描述。
    """
    @staticmethod
    def describe_chronic_tension(score: float) -> str:
        if score < 0.3:
            return "从长期来看，你的血压整体比较平稳。"
        elif score < 0.6:
            return "从长期来看，你的血压有一点偏高，建议继续保持良好的生活习惯。"
        else:
            return "从长期来看，你的血压偏高一些，建议按医生的随访计划继续管理。"

    @staticmethod
    def describe_acute_push(score: float) -> str:
        if score < 0.3:
            return "最近一两天血压变化不大，可以按平常节奏生活。"
        elif score < 0.6:
            return "最近一两天血压有些起伏，建议这几天多注意休息。"
        else:
            return "最近一两天血压变化比较明显，如果你感觉不舒服，请尽快告诉家人。"

    @staticmethod
    def describe_plaque_risk(plaque_risk: Dict) -> List[str]:
        if plaque_risk.get("level") in ["high", "moderate"]:
            return [
                "",
                "【长期健康提示】",
                "您目前的血压模式可能会给血管带来一些额外的压力。",
                "这不代表有立刻的危险，但在下次复诊时，和医生聊一聊这个情况会很有帮助。"
            ]
        return []

# ==========================
# 提示语引擎 (Prompt Engine)
# ==========================

class NarrativeState:
    """叙事状态基类"""
    def __init__(self, steady_result: Dict, risk_bundle: Dict):
        self.steady_result = steady_result
        self.risk_bundle = risk_bundle
        self.long_data = risk_bundle.get("longitudinal", {})
        self.text_buffer = []

    def build(self) -> str:
        """构建报告的模板方法"""
        self.add_header()
        self.add_core_analysis()
        self.add_contextual_advice()
        self.add_footer()
        return "\n".join(self.text_buffer)

    def add_header(self):
        """默认头部"""
        # 粘性设计 1: 强调累计天数和连胜纪录
        total_days = self.long_data.get("total_days", 0)
        streak = self.long_data.get("current_streak", 1)
        
        cycle_info = self.long_data.get("cycle_info", {})
        cycle_day = cycle_info.get("day_in_cycle", 1)
        
        header_text = f"【档案第 {total_days} 天】"
        if streak > 1:
            header_text += f" 🔥已连续打卡 {streak} 天"
            
        self.text_buffer.append(header_text)
        
        if cycle_info.get("is_complete", False):
            self.text_buffer.append(f"🎉 恭喜！您刚刚完成了一个完整的 7 天监测周期！")
            self.text_buffer.append("每一次完整的记录，都让AI模型对您的了解更深一步。")

    def add_core_analysis(self):
        """默认核心分析"""
        trend_lines = _explain_trend(self.steady_result)
        self.text_buffer.append("最近你的血压整体情况如下：")
        for line in trend_lines:
            self.text_buffer.append(f"- {line}")
        self.text_buffer.append("")

    def add_contextual_advice(self):
        """由具体状态重写"""
        pass

    def add_footer(self):
        """默认页脚和留存钩子"""
        self.text_buffer.append("")
        self.text_buffer.append("【专属健康管家】")
        self.text_buffer.append("健康管理是一场马拉松。坚持记录和分析，")
        self.text_buffer.append("能让我们更早发现潜在问题。您的每一次测量，都在为健康加分。")


class CriticalState(NarrativeState):
    """状态：高危或危急风险"""
    def build(self) -> str:
        # 重写 build 以直接返回警报
        return "【警报】系统检测到您的血压或身体状况存在较高风险。\n请立即停止当前活动，保持静坐或卧床休息。\n请尽快告知家属或联系医生，并出示本报告。"


class OnboardingState(NarrativeState):
    """状态：第 1-3 天 (阶段 1)"""
    def add_header(self):
        # 覆盖默认头部，Onboarding 阶段要极度热情
        self.text_buffer.append("👋 欢迎开启心脏健康之旅！")
        
        # 粘性设计 2: 明确的进度条反馈
        base_info = self.steady_result.get("base", {}).get("band", {})
        needed = base_info.get("records_needed", 0)
        
        if needed > 0:
            self.text_buffer.append(f"🚀 个性化模型构建中... 还需 {needed} 次测量即可解锁【专属稳态带】分析。")
        else:
            self.text_buffer.append("✨ 太棒了！您的基础数据已集齐，个性化模型已激活。")

    def add_contextual_advice(self):
        self.text_buffer.append("💡 新手小贴士：")
        self.text_buffer.append("现在的每一条数据都是您健康档案的基石。建议明天同一时间继续测量，帮助我们学习您的身体节律。")


class BaselineState(NarrativeState):
    """状态：第 4-14 天 (阶段 2)"""
    def add_header(self):
        super().add_header()
        self.text_buffer.append("📊 您的稳态区间正在确认中。")

    def add_contextual_advice(self):
        chronic = self.risk_bundle.get("chronic_tension", 0)
        if chronic < 0.3:
            self.text_buffer.append("初步数据显示，您的基础血压表现平稳。")
        else:
            self.text_buffer.append("初步数据显示，您的基础血压存在一定波动，我们将继续密切追踪。")


class HabitState(NarrativeState):
    """状态：第 15-30 天 (阶段 3)"""
    def add_header(self):
        # 粘性设计 3: 利用损失厌恶 (Loss Aversion) 维护连胜
        streak = self.long_data.get("current_streak", 1)
        self.text_buffer.append(f"🌱 习惯养成挑战：连续 {streak} 天达成！")
        if streak > 3:
            self.text_buffer.append("保持这个节奏，不要让连胜中断哦！")

    def add_contextual_advice(self):
        continuity = self.long_data.get("continuity_score", 0)
        if continuity > 0.8:
            self.text_buffer.append("🌟 您的自律令人印象深刻！")
            self.text_buffer.append("这种高质量的连续数据，能让医生瞬间看懂您的血压规律。")
        else:
            self.text_buffer.append("📅 补卡提醒：")
            self.text_buffer.append("数据出现了一些断档。为了不影响趋势预测的准确性，建议明天记得回来测量。")


class StandardState(NarrativeState):
    """状态：第 31+ 天 (阶段 4, 5, 6) - 标准详细报告"""
    def add_contextual_advice(self):
        # 1. 慢性张力
        chronic = self.risk_bundle.get("chronic_tension", 0)
        self.text_buffer.append(RiskExpressionEngine.describe_chronic_tension(chronic))

        # 2. 急性推力
        acute = self.risk_bundle.get("acute_push", 0)
        self.text_buffer.append(RiskExpressionEngine.describe_acute_push(acute))

        # 3. 血管状态
        vascular = _analyze_vascular_status(self.steady_result)
        if vascular:
            self.text_buffer.append("")
            self.text_buffer.append("【血管健康状态】")
            self.text_buffer.append(f"您的脉压差（高压减低压）约为 {int(vascular['value'])} mmHg。")
            self.text_buffer.append(vascular['status'])

        # 4. 斑块风险
        plaque = self.risk_bundle.get("plaque_risk", {})
        self.text_buffer.extend(RiskExpressionEngine.describe_plaque_risk(plaque))


class PromptEngine:
    """
    提示语引擎 (Prompt Engine)
    根据风险和生命周期上下文选择合适的状态处理程序。
    """
    def __init__(self, steady_result, risk_bundle):
        self.steady_result = steady_result
        self.risk_bundle = risk_bundle
        self.long_data = risk_bundle.get("longitudinal", {})

    def get_state_handler(self) -> NarrativeState:
        # 1. 安全第一：高危/危急风险覆盖一切
        acute_level = self.risk_bundle.get("acute_risk_level")
        if acute_level in ("critical", "high"):
            return CriticalState(self.steady_result, self.risk_bundle)

        # 2. 生命周期阶段
        ux_phase = self.long_data.get("ux_phase", PHASE_1_ONBOARDING)
        
        if ux_phase == PHASE_1_ONBOARDING:
            return OnboardingState(self.steady_result, self.risk_bundle)
        elif ux_phase == PHASE_2_BASELINE:
            return BaselineState(self.steady_result, self.risk_bundle)
        elif ux_phase == PHASE_3_HABIT:
            return HabitState(self.steady_result, self.risk_bundle)
        else:
            # 阶段 4, 5, 6 使用标准详细报告
            return StandardState(self.steady_result, self.risk_bundle)

    def generate(self) -> str:
        handler = self.get_state_handler()
        return handler.build()


def _generate_user_text(steady_result, risk_bundle):
    """使用状态机引擎生成用户文本的入口点"""
    engine = PromptEngine(steady_result, risk_bundle)
    return engine.generate()


# ==========================
# 家属版（严谨 + 行动建议）
# ==========================

def _generate_family_text(steady_result, risk_bundle):
    trend_lines = _explain_trend(steady_result)

    chronic = risk_bundle["chronic_tension"]
    acute = risk_bundle["acute_push"]
    acute_level = risk_bundle["acute_risk_level"]
    symptom_level = risk_bundle["symptom_level"]

    # 获取纵向数据用于监督
    long_data = risk_bundle.get("longitudinal", {})
    streak = long_data.get("current_streak", 0)
    continuity = long_data.get("continuity_score", 1.0)
    
    text = []

    # --- 1. 状态红绿灯 (Headlines) ---
    if acute_level in ("critical", "high"):
        text.append("🚨 【紧急关注】")
        text.append("本周期的监测数据显示：老人的心血管负荷显著升高。")
        text.append("请放下手头的工作，立即确认老人的身体状况。")
    elif acute_level == "moderate_high":
        text.append("⚠️ 【重点留意】")
        text.append("近期血压出现较为明显的波动，尚未达到危险程度，但需要家属介入干预。")
    elif acute_level == "moderate":
        text.append("👀 【需要关注】")
        text.append("血压有一些起伏，可能与近期天气、情绪或睡眠有关。")
    else:
        text.append("✅ 【状态平稳】")
        text.append("老人的血压控制得不错，请继续保持。")
    
    text.append("")

    # --- 2. 监督与反馈 (Engagement) ---
    text.append("📋 【家属监督任务】")
    if streak > 3:
        text.append(f"🌟 表扬：老人已经连续 {streak} 天坚持测量了！")
        text.append("建议您发个微信或打个电话夸夸他/她，这种正向鼓励能让老人坚持得更好。")
    elif continuity < 0.6:
        text.append("📅 提醒：近期测量不太规律，容易漏掉关键的风险信号。")
        text.append("建议您设定一个闹钟，在每天固定的时间（如早饭前）提醒老人测量。")
    else:
        text.append("👍 维持：目前的测量频率符合要求，请协助老人继续保持。")
    
    text.append("")

    # --- 3. 情况详解 (Explanation) ---
    text.append("🔍 【详细情况解读】")
    text.append("近期变化趋势：")
    for line in trend_lines:
        text.append(f"- {line}")

    # 慢性张力 (通俗化)
    text.append("长期基础（血管底子）：")
    if chronic < 0.3:
        text.append("- 🟢 负担很轻：血管状态保持得很好。")
    elif chronic < 0.6:
        text.append("- 🟡 负担中等：属于慢病管理的正常范围，只要不剧烈波动就没事。")
    else:
        text.append("- 🔴 负担较重：血管壁长期承受较高压力，就像发动机长期高转速运转，需要倍加呵护。")

    # 急性推力 (通俗化)
    text.append("近期波动（当下路况）：")
    if acute < 0.3:
        text.append("- 🟢 风平浪静：最近一两天非常平稳。")
    elif acute < 0.6:
        text.append("- 🟡 有点颠簸：最近一两天有波动，可能是没睡好或情绪波动。")
    else:
        text.append("- 🔴 剧烈震荡：最近一两天波动很大，是风险最高的时刻。")

    text.append("")

    # --- 4. 行动指南 (Call to Action) ---
    text.append("🛡️ 【您现在需要做什么？】")
    
    if acute_level == "moderate":
        text.append("1. 提醒老人按时吃药，不要因为觉得没事就停药。")
        text.append("2. 这两天多喝水，保持大便通畅。")
        text.append("3. 继续观察明天的测量数据。")

    elif acute_level == "moderate_high":
        text.append("1. 询问老人最近是否有什么烦心事，或者睡眠不好。")
        text.append("2. 建议明天早晚各测一次，如果连续两天偏高，建议去门诊调整用药。")
        text.append("3. 叮嘱饮食清淡，这两天少吃咸的。")

    elif acute_level in ("critical", "high"):
        text.append("1. 立即联系老人，询问有无头晕、胸闷、肢体无力等感觉。")
        if symptom_level in ("high", "medium"):
            text.append("2. 【重要】因伴有不适症状，建议直接前往急诊或拨打急救电话，不要拖延。")
        else:
            text.append("2. 即使没有症状，也建议明天一早去社区医院复查血压。")
        text.append("3. 检查药盒，确认最近是否漏服了降压药。")
        
        # --- 针对低灌注风险的特殊提示 ---
        if "hypoperfusion_risk" in risk_bundle.get("assessment_reasons", []):
            text.append("【特别注意】检测到血压相对于长期基线出现显著下降（低灌注）。")
            text.append("对于长期高血压患者，血压过低可能导致脑部或心脏供血不足。请确认是否服药过量或有脱水、心脏不适等情况。")
            
    else: # low
        text.append("1. 目前一切正常，不需要额外干预。")
        text.append("2. 周末回家时，可以带点老人爱吃的水果，让他/她保持心情愉快。")

    # 血管物理变化解释
    vascular = _analyze_vascular_status(steady_result)
    if vascular:
        text.append("")
        text.append("【血管物理特性分析】")
        text.append(f"当前脉压差：{int(vascular['value'])} mmHg。")
        text.append(f"状态评估：{vascular['status']}")
        text.append(f"近期变化：{vascular['trend']}")

    # 斑块稳定性风险提示 (新增)
    plaque = risk_bundle.get("plaque_risk", {})
    if plaque.get("level") in ["high", "moderate"]:
        text.append("")
        text.append("💡 【医生想对您说】")
        plaque_reasons = plaque.get("reasons", [])
        reason_map = {
            "high_pulse_pressure": "脉压差过大",
            "high_bp_variability": "血压波动剧烈",
            "morning_surge": "晨峰现象",
        }
        translated_reasons = [reason_map.get(r, "") for r in plaque_reasons if r in reason_map]
        
        if translated_reasons:
             text.append(f"虽然今天没有急性风险，但分析显示，老人存在一些可能增加远期风险的血压模式（如{'、'.join(translated_reasons)}）。")
        
        text.append("这些模式会增加对血管壁的长期压力。建议下次陪老人去医院开药时，把这个报告拿给医生看，医生可能会微调药量来保护血管。")

    # 订阅/留存 激励话术 (新增)
    text.append("")
    text.append("❤️ 【给家属的悄悄话】")
    text.append("老人的健康不仅需要药物，更需要关注。")
    text.append("您的每一次查看和转发，都是对老人最好的心理支持。请协助老人保持测量，这份连续的记录在关键时刻将价值连城。")

    return "\n".join(text)


# ==========================
# 医生版（结构化 + 时间序列）
# ==========================

def _generate_doctor_text(records, steady_result, risk_bundle, figure_paths):
    text = []

    # 时间序列
    text.append("## 时间序列概览")
    if records:
        # 兼容 timestamp
        start_time = records[0].get('datetime') or records[0].get('timestamp')
        end_time = records[-1].get('datetime') or records[-1].get('timestamp')
        text.append(f"- 记录起始时间：{_fmt(start_time)}")
        text.append(f"- 最近一次记录：{_fmt(end_time)}")
        text.append(f"- 总记录数：{len(records)}")
    else:
        text.append("- 无可用记录")
    text.append("")

    # 基线 vs 近期（优先使用 30w 窗口；若不存在则回退）
    base = None
    recent = None
    win_label = "N/A"
    
    try:
        for k in ["30pt", "20pt", "10pt", "5pt", "3pt"]:
            if k in steady_result.get("windows", {}):
                win = steady_result["windows"][k]
                base = win.get("baseline")
                recent = win.get("recent")
                win_label = k
                break
    except Exception:
        base = None
        recent = None

    if base and recent:
        text.append(f"## 基线与近期稳态（{win_label} 窗口）")
        text.append(f"- 基线区间：{_fmt(base['start'])} → {_fmt(base['end'])}")
        text.append(f"- 近期区间：{_fmt(recent['start'])} → {_fmt(recent['end'])}")
        text.append(f"- 基线稳态稳定性：{base.get('stability', 0.0):.3f}")
        text.append(f"- 近期稳态稳定性：{recent.get('stability', 0.0):.3f}")
        text.append("- 基线中位数：")
        for m, v in base.get("profile", {}).items():
            text.append(f"  - {m.upper()}: {v.get('median', 0.0):.1f}")
        text.append("- 最近中位数：")
        for m, v in recent.get("profile", {}).items():
            text.append(f"  - {m.upper()}: {v.get('median', 0.0):.1f}")
        text.append("")
    else:
        text.append("## 基线与近期稳态")
        text.append("- 提示：样本量不足以生成稳态对比。")
        text.append("")

    # 稳态分段
    text.append("## 稳态分段（全程）")
    segments = steady_result.get("segments", [])
    if not segments:
        text.append("- 无有效稳态分段。")
        text.append("")
    else:
        for i, seg in enumerate(segments):
            seg_type = seg.get("type", "unknown").upper()
            
            text.append(f"### 段 {i+1} ({seg_type})")
            text.append(f"- 时间：{_fmt(seg['start'])} → {_fmt(seg['end'])}")
            text.append(f"- N：{seg.get('count', 0)}")
            text.append(f"- 稳定性：{seg.get('stability', 0.0):.3f}")
            text.append("- 中位数：")
            for m, v in seg.get("profile", {}).items():
                text.append(f"  - {m.upper()}: {v.get('median', 0.0):.1f}")
            text.append("")

    # 风险评分
    text.append("## 风险评分（供参考）")
    text.append(f"- 慢性张力评分：{risk_bundle.get('chronic_tension', 0.0):.2f}")
    text.append(f"- 短期动力学推力：{risk_bundle.get('acute_push', 0.0):.2f}")
    text.append(f"- 症状等级：{risk_bundle.get('symptom_level', 'none')}")
    text.append(f"- 急性风险分层：{risk_bundle.get('acute_risk_level', 'low')}")
    text.append(f"- 监测依从性风险：{risk_bundle.get('gap_risk', 0.0):.2f}")
    text.append("")

    # 纵向依从性 (New)
    long_data = risk_bundle.get("longitudinal", {})
    if long_data:
        text.append("## 纵向依从性 (Longitudinal Adherence)")
        text.append(f"- **User Stage**: {long_data.get('stage', 'unknown').upper()}")
        text.append(f"- **Maturity**: {long_data.get('maturity_level', 'L1')}")
        text.append(f"- **Active Days**: {long_data.get('days_active', 0)}")
        text.append(f"- **Continuity Score**: {long_data.get('continuity_score', 0):.2f}")
        text.append("")

    # 脉压差分析 (新增)
    vascular = _analyze_vascular_status(steady_result)
    if vascular:
        text.append("## 脉压差分析 (Pulse Pressure)")
        text.append(f"- **当前脉压差**: {int(vascular['value'])} mmHg")
        text.append(f"- **状态评估**: {vascular['status']}")
        text.append(f"- **近期趋势**: {vascular['trend']}")
        text.append("")

    # 动脉风险评估 (原斑块稳定性风险)
    plaque = risk_bundle.get("plaque_risk", {})
    if plaque.get("score", 0.0) > 0:
        text.append("## 动脉风险评估 (Arterial Risk)")
        text.append(f"- **风险等级**: {plaque.get('level', 'low').upper()} (评分: {plaque.get('score', 0):.2f})")
        text.append(f"- **风险因素**: {', '.join(plaque.get('reasons', []))}")
        text.append("")

    # 血压模式分析
    patterns = figure_paths.get("patterns", {})
    text.append("## 血压模式分析（Patterns）")
    dip = patterns.get("nocturnal_dip", "N/A")
    surge = patterns.get("morning_surge", "N/A")
    variability = patterns.get("variability", "N/A")
    text.append(f"- 夜间血压下降类型：{dip}")
    text.append(f"- 晨峰：{surge}")
    text.append(f"- 血压波动性：{variability}")
    text.append("")

    # 可视化图表 (嵌入 HTML)
    chart_index = 1

    if "scatter_url" in figure_paths and figure_paths["scatter_url"]:
        text.append(f"## {chart_index}. 血压分布与风险分级 (BP Distribution)")
        text.append("展示收缩压与舒张压的分布情况，背景色块对应高血压风险分级（绿色正常，红色高危）。")
        text.append(f'<img src="{figure_paths["scatter_url"]}" style="width:100%; max-width:600px; border-radius:8px; margin: 10px 0; border:1px solid #eee;">')
        chart_index += 1

    if "time_series_url" in figure_paths and figure_paths["time_series_url"]:
        text.append(f"## {chart_index}. 血压走势与事件标记 (Time Series)")
        text.append("展示血压随时间的变化，标注了稳态段（背景色）、急性事件（红点）及症状（黄点）。")
        text.append(f'<img src="{figure_paths["time_series_url"]}" style="width:100%; max-width:600px; border-radius:8px; margin: 10px 0; border:1px solid #eee;">')
        chart_index += 1

    if "trajectory_url" in figure_paths and figure_paths["trajectory_url"]:
        text.append(f"## {chart_index}. 多窗口轨迹分析 (Trajectory)")
        text.append("展示不同时间窗口（如3次、5次、10次记录）内血压相对于基线的变化幅度，用于判断趋势性质。")
        text.append(f'<img src="{figure_paths["trajectory_url"]}" style="width:100%; max-width:600px; border-radius:8px; margin: 10px 0; border:1px solid #eee;">')
        chart_index += 1

    if "volatility_url" in figure_paths and figure_paths["volatility_url"]:
        text.append(f"## {chart_index}. 血压波动性趋势 (Volatility Trend)")
        text.append("展示血压波动范围（IQR）随时间的变化趋势，反映血管调节能力的稳定性。")
        text.append(f'<img src="{figure_paths["volatility_url"]}" style="width:100%; max-width:600px; border-radius:8px; margin: 10px 0; border:1px solid #eee;">')
        chart_index += 1

    # 增加专业价值提示 (新增)
    text.append("")
    text.append("---")
    text.append("**System Note**: Continuous longitudinal monitoring allows for better assessment of BPV (Blood Pressure Variability) and treatment response.")

    return "\n".join(text)


# ==========================
# 主入口
# ==========================

def generate_language_blocks(records, steady_result, risk_bundle, figure_paths):
    return {
        "user": _generate_user_text(steady_result, risk_bundle),
        "family": _generate_family_text(steady_result, risk_bundle),
        "doctor": _generate_doctor_text(records, steady_result, risk_bundle, figure_paths),
    }
