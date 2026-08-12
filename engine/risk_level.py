from .lifecycle import calculate_lifecycle_state

HIGH_RISK_SYMPTOMS = {"chest_pain", "weakness_one_side", "slurred_speech", "vision_loss", "confusion", "thunderclap_headache"}
MEDIUM_RISK_SYMPTOMS = {"chest_tightness", "dizzy", "palpitations", "short_breath", "severe_headache"}

# ★ 新增：既往病史里，哪些算"高危心血管病史"——有这些病史的人，Path B的
# 判定门槛会相应调低，更容易触发"建议立即就医"。跟UserProfile.wxml这次
# 新增的心血管细分选项对应。
HIGH_RISK_HISTORY_ITEMS = {
    "冠心病", "心肌梗死", "心律失常/房颤", "心力衰竭", "脑卒中(中风)", "心脏支架/搭桥手术史"
}
HIGH_RISK_HISTORY_DISCOUNT = 0.7  # 用于(b)短期变化速度这类"增量"阈值——按比例打折依然有意义
# ★ 修复：(c)绝对阈值、(d)低灌注阈值是"具体数值"，不能用百分比打折——
# 170×0.7=119这种结果本身就不合理(119mmHg基本是正常范围)，会导致有高危
# 病史的人几乎任何一次读数都被判定"立即就医"，Path A的渐进分级形同虚设。
# 具体数值型阈值改用固定下调量，170→155这种降幅才有意义。
HIGH_RISK_HISTORY_SBP_OFFSET = 15.0
HIGH_RISK_HISTORY_DBP_OFFSET = 8.0
HIGH_RISK_HISTORY_HYPO_OFFSET = 10.0

# ★ 新增：年龄性别分层——先留成可配置占位结构，不接入任何判断逻辑。
# 等有确认的分层数值(参考中国高血压指南/ACC-AHA/ESC-ESH等，需要用户核实
# 具体版本后拍板)再往这里填，届时在_path_a_tier/_path_b_triggers里读取使用。
AGE_SEX_PROFILE_OVERRIDES = {
    # 示例结构(未启用，仅占位)：
    # "elderly_65_79": {"sbp_target_upper": 139, "absolute_sbp_threshold": 160},
    # "elderly_80_plus": {"sbp_target_upper": 149, "absolute_sbp_threshold": 150},
}

# Path B(c)：绝对阈值——静态极值本身就该建议就医，不需要症状或趋势陪同
ABSOLUTE_SBP_THRESHOLD = 170
ABSOLUTE_DBP_THRESHOLD = 105

# Path A分档：SBP偏离band的绝对值兜底——低于这个mmHg数，不管比例算出来
# 多高，都强制算"低"，避免IQR过小的人一点点噪声被放大成好几倍IQR
PATH_A_MIN_ABS_DEVIATION = 5.0

# Path A内部三档 -> 对外兼容旧英文枚举值的映射(给尚未升级的前端/图表模块用)
PATH_A_LEVEL_MAP = {"低": "low", "关注": "moderate", "中": "moderate_high"}


def _get_val(obj, key, default=0):
    """辅助函数：安全获取对象属性或字典值"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _has_high_risk_history(health_history):
    if not health_history:
        return False
    return any(item in HIGH_RISK_HISTORY_ITEMS for item in health_history)


def _extract_context(records, steady_data, events_by_segment):
    """步骤1：提取分析所需的上下文数据"""
    def _get_sort_key(x):
        return _get_val(x, 'datetime') or _get_val(x, 'timestamp') or ""

    latest = sorted(records, key=_get_sort_key)[-1]

    sbp = float(_get_val(latest, 'sbp', 120))
    dbp = float(_get_val(latest, 'dbp', 80))
    hr = float(_get_val(latest, 'hr', 70))

    # ★ 修复：症状只能看"这次测量"本身提交的，不能往前翻整个窗口。
    # events_by_segment(steady_state.py算的)汇总的是"最近一整个窗口(可能
    # 是最近20-30条记录)里出现过的所有症状"，是完全不同的东西——之前这里
    # 把两者merge在一起，会导致哪怕是几周前某一次测量时勾选过的症状，只要
    # 还落在窗口范围内，这次分析都会被当成"这次也有症状"，产生"您提到了
    # 身体不适"这种失实的文案，跟当前这次测量完全无关。不再merge，
    # current_symptoms只取latest这一条记录自己的symptoms/events字段。
    raw_evs = _get_val(latest, 'events', []) or _get_val(latest, 'symptoms', [])
    current_symptoms = [str(e).lower().strip() for e in raw_evs] if isinstance(raw_evs, list) else []

    # ★ 改：不再从steady_data["base"]取单一SBP标量+对称band，改用
    # steady_state.py这次新增的bands(多指标非对称band)/current_deviation
    # (当前值偏离band的比例)——这两个是这次重构的核心产出
    bands = _get_val(steady_data, 'bands', {}) or {}
    current_deviation = _get_val(steady_data, 'current_deviation', {}) or {}

    return {
        "sbp": sbp,
        "dbp": dbp,
        "hr": hr,
        "pp": sbp - dbp,
        "symptoms": current_symptoms,
        "bands": bands,
        "current_deviation": current_deviation,
    }


def _path_a_tier(ctx):
    """
    Path A(默认/渐进式)：按SBP偏离band的程度分低/关注/中三档
    (deviation_ratio<0.5低，0.5~1.0关注，>=1.0已突破band即中)。
    DBP同步偏离时，"关注"可以升级成"中"(两个独立指标都偏，比只有一个
    更可信，跟steady_state.py分段确认时"多指标同步"是同一个思路)。
    加绝对值兜底：SBP实际偏离不到PATH_A_MIN_ABS_DEVIATION，不管比例
    多高都强制算"低"，避免IQR过小导致的假阳性。
    """
    sbp_band = ctx["bands"].get("sbp")
    if sbp_band is None:
        return "低"

    sbp_ratio = ctx["current_deviation"].get("sbp", 0.0)
    dbp_ratio = ctx["current_deviation"].get("dbp", 0.0)

    abs_dev = abs(ctx["sbp"] - sbp_band["median"])
    if abs_dev < PATH_A_MIN_ABS_DEVIATION:
        return "低"

    if sbp_ratio < 0.5:
        tier = "低"
    elif sbp_ratio < 1.0:
        tier = "关注"
    else:
        tier = "中"

    if tier == "关注" and dbp_ratio >= 0.5:
        tier = "中"

    return tier


def _path_b_triggers(ctx, emergency_info, health_history):
    """
    Path B(优先/特例，命中任意一条都直接判定需要就医，跳过Path A的渐进评分)：
    (a) symptom_only —— 仅凭高危症状本身即可直接触发，不需要数值也剧变
    (b) acute_shift_symptom —— 数值突然剧升/剧降(emergency_info的短期
        变化信号) + 症状(至少中危症状)同时出现
    (c) absolute_threshold —— 静态绝对阈值，不需要症状/趋势陪同
    (d) hypoperfusion —— 基线一直很高的人突然降到偏低值，是独立的危险模式

    有高危心血管病史时，(b)(c)(d)的判定门槛按HIGH_RISK_HISTORY_DISCOUNT
    打折，更容易触发。(a)不受病史影响——高危症状本身已经足够严重独立成立，
    不需要再靠病史加码判断。
    """
    symptoms = ctx["symptoms"]
    has_high_risk_symptom = any(s in HIGH_RISK_SYMPTOMS for s in symptoms)
    has_med_risk_symptom = any(s in MEDIUM_RISK_SYMPTOMS for s in symptoms)
    sensitive = _has_high_risk_history(health_history)
    discount = HIGH_RISK_HISTORY_DISCOUNT if sensitive else 1.0

    triggers = []

    # (a) 高危症状独立触发
    if has_high_risk_symptom:
        triggers.append("symptom_only")

    # (b) 数值剧变 + 症状(至少中危)——emergency_info由cardiovascular_engine.py
    #     的emergency.py模块算好传进来，这里重新看它的原始短期变化数值，
    #     而不是只信它的emergency标志位，因为有高危病史时阈值要打折，
    #     不能直接用emergency_info算好的、没考虑病史的固定阈值判断
    emergency_flag = False
    if emergency_info:
        changes = emergency_info.get("short_term_changes", {}) or {}
        dsbp = abs(changes.get("dsbp", 0) or 0)
        ddbp = abs(changes.get("ddbp", 0) or 0)
        dpp = abs(changes.get("dpp", 0) or 0)
        if dsbp >= 20 * discount or ddbp >= 15 * discount or dpp >= 15 * discount:
            emergency_flag = True
        elif emergency_info.get("synchronous_shift") or emergency_info.get("instability"):
            emergency_flag = True
    if emergency_flag and (has_high_risk_symptom or has_med_risk_symptom):
        triggers.append("acute_shift_symptom")

    # (c) 绝对阈值(静态极值，不需要症状/趋势陪同)——用固定下调量，不用百分比打折
    sbp_th = ABSOLUTE_SBP_THRESHOLD - (HIGH_RISK_HISTORY_SBP_OFFSET if sensitive else 0)
    dbp_th = ABSOLUTE_DBP_THRESHOLD - (HIGH_RISK_HISTORY_DBP_OFFSET if sensitive else 0)
    if ctx["sbp"] >= sbp_th or ctx["dbp"] >= dbp_th:
        triggers.append("absolute_threshold")

    # (d) 高基线低灌注——基线一直很高，这次却突然降到偏低值。同样用固定
    # 上调量(不是除以discount)，避免阈值反而超过基线本身导致规则失效
    sbp_band = ctx["bands"].get("sbp")
    if sbp_band:
        base_sbp = sbp_band["median"]
        hypo_th = 115 + (HIGH_RISK_HISTORY_HYPO_OFFSET if sensitive else 0)
        if base_sbp >= 150 and ctx["sbp"] <= hypo_th:
            triggers.append("hypoperfusion")

    return triggers


def _assess_plaque_risk(ctx, patterns):
    """
    评估血流动力学对动脉斑块的机械压力风险 (Hemodynamic Stress on Plaques)
    注意：这是基于物理参数的推断，非影像学诊断。独立维度，不受Path A/B影响。
    """
    risk_score = 0.0
    reasons = []

    pp = ctx["pp"]
    sbp = ctx["sbp"]
    hr = ctx.get("hr", 70)

    # 1. 脉压差 (Pulsatile Stress) - 权重最高
    if pp >= 60:
        risk_score += 0.4
        reasons.append("high_pulse_pressure")
    elif pp >= 50:
        risk_score += 0.2

    # 2. 血压波动性 (Shear Stress Fluctuation)
    variability = patterns.get("variability", "low") if patterns else "low"
    if variability == "high":
        risk_score += 0.3
        reasons.append("high_bp_variability")
    elif variability == "medium":
        risk_score += 0.1

    # 3. 晨峰 (Trigger) - 斑块破裂高危时刻
    surge = patterns.get("morning_surge", "absent") if patterns else "absent"
    if surge == "present":
        risk_score += 0.2
        reasons.append("morning_surge")

    # 4. 心率 (Frequency) - 冲击频率
    if hr > 90:
        risk_score += 0.1
        reasons.append("tachycardia_stress")

    # 5. 绝对高压 (Wall Tension)
    if sbp > 160:
        risk_score += 0.2
        reasons.append("high_wall_tension")

    risk_score = min(1.0, risk_score)

    level = "low"
    if risk_score >= 0.7:
        level = "high"
    elif risk_score >= 0.4:
        level = "moderate"

    return {"score": risk_score, "level": level, "reasons": reasons}


def assess_risk_bundle(records, steady_data, events_by_segment, patterns=None, emergency_info=None, health_history=None):
    """
    ★ 改：函数签名新增emergency_info(真·急性信号，之前算出来从未被用上)
    和health_history(既往病史，用于调低Path B的判定门槛)两个参数。
    整体判断逻辑从"两个分数(acute_push/chronic_tension)加权比大小"
    改成两条路径：Path A(默认/渐进式，按偏离band的程度分低/关注/中)、
    Path B(优先/特例，命中任意触发条件直接判定需要就医，跳过Path A)。
    """
    if not records:
        return {
            "acute_risk_level": "low",
            "path": "A",
            "tier": "低",
            "path_b_triggers": [],
            "symptom_level": "none",
            "plaque_risk": {},
            "longitudinal": calculate_lifecycle_state([]),
            "assessment_reasons": [],
            "has_high_risk_history": False,
        }

    ctx = _extract_context(records, steady_data, events_by_segment)

    path_b_triggers = _path_b_triggers(ctx, emergency_info, health_history)

    if path_b_triggers:
        path = "B"
        tier = None
        flat_level = "critical"
        reasons = path_b_triggers
    else:
        path = "A"
        tier = _path_a_tier(ctx)
        flat_level = PATH_A_LEVEL_MAP.get(tier, "low")
        reasons = [f"path_a_{tier}"]

    has_high_risk_symptom = any(s in HIGH_RISK_SYMPTOMS for s in ctx["symptoms"])
    has_med_risk_symptom = any(s in MEDIUM_RISK_SYMPTOMS for s in ctx["symptoms"])
    symptom_level = "high" if has_high_risk_symptom else ("medium" if has_med_risk_symptom else "none")

    plaque_risk = _assess_plaque_risk(ctx, patterns)
    longitudinal = calculate_lifecycle_state(records)

    print(
        f"DEBUG_RISK >>> SBP:{ctx['sbp']} Path:{path} Tier:{tier} "
        f"Triggers:{path_b_triggers} | Plaque:{plaque_risk.get('level')} | "
        f"Stage:{longitudinal.get('stage')}",
        flush=True
    )

    return {
        # 兼容旧字段名+旧英文枚举值(low/moderate/moderate_high/critical)，
        # 供尚未跟着这次重构一起升级的前端/图表模块继续读取，不会因为这次
        # 改动直接崩掉
        "acute_risk_level": flat_level,
        # 以下是这次重构新增的字段，language.py(下一步)会改用这些
        "path": path,                        # "A" 或 "B"
        "tier": tier,                        # Path A内部"低"/"关注"/"中"，Path B时为None
        "path_b_triggers": path_b_triggers,  # Path B命中了哪几条(可能不止一条)
        "assessment_reasons": reasons,
        "symptom_level": symptom_level,
        "plaque_risk": plaque_risk,
        "longitudinal": longitudinal,
        "has_high_risk_history": _has_high_risk_history(health_history),
    }