from datetime import datetime
from engine.lifecycle import calculate_lifecycle_state

HIGH_RISK_SYMPTOMS = {"chest_pain", "weakness_one_side", "slurred_speech", "vision_loss", "confusion", "thunderclap_headache"}
MEDIUM_RISK_SYMPTOMS = {"chest_tightness", "dizzy", "palpitations", "short_breath", "severe_headache"}

def _get_val(obj, key, default=0):
    """辅助函数：安全获取对象属性或字典值"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _extract_context(records, steady_data, events_by_segment):
    """步骤1：提取分析所需的上下文数据"""
    # 兼容 datetime 和 timestamp 字段进行排序
    def _get_sort_key(x):
        return _get_val(x, 'datetime') or _get_val(x, 'timestamp') or ""
        
    latest = sorted(records, key=_get_sort_key)[-1]
    
    sbp = float(_get_val(latest, 'sbp', 120))
    dbp = float(_get_val(latest, 'dbp', 80))
    hr = float(_get_val(latest, 'hr', 70))
    
    # 提取症状
    raw_evs = _get_val(latest, 'events', []) or _get_val(latest, 'symptoms', [])
    current_symptoms = [str(e).lower().strip() for e in raw_evs] if isinstance(raw_evs, list) else []

    # 合并 events_by_segment 中的最新症状
    if events_by_segment and isinstance(events_by_segment, list) and len(events_by_segment) > 0:
        recent_segment_events = events_by_segment[-1]
        if isinstance(recent_segment_events, list):
            for e in recent_segment_events:
                s_clean = str(e).lower().strip()
                if s_clean not in current_symptoms:
                    current_symptoms.append(s_clean)
    
    # 提取基线和趋势
    base_info = _get_val(steady_data, 'base', {})
    base_sbp = _get_val(base_info, 'sbp', 120.0)
    if base_sbp is None: base_sbp = 120.0
    
    # 提取个体化稳态带
    band_info = _get_val(base_info, 'band', {})
    
    trend_info = _get_val(steady_data, 'trend', {})
    sbp_trend = _get_val(trend_info, 'sbp', 'stable')

    return {
        "sbp": sbp,
        "dbp": dbp,
        "hr": hr,
        "pp": sbp - dbp,
        "symptoms": current_symptoms,
        "base_sbp": base_sbp,
        "band": band_info,
        "sbp_trend": sbp_trend
    }

def _evaluate_risk_level(ctx):
    """步骤2：核心风险判定逻辑"""
    sbp = ctx["sbp"]
    dbp = ctx["dbp"]
    pp = ctx["pp"]
    base_sbp = ctx["base_sbp"]
    band = ctx.get("band", {})
    symptoms = ctx["symptoms"]
    
    risk_level = "low"
    reasons = []
    
    has_high_risk = any(s in HIGH_RISK_SYMPTOMS for s in symptoms)
    has_med_risk = any(s in MEDIUM_RISK_SYMPTOMS for s in symptoms)
    
    # 1. 症状判定
    if has_high_risk:
        risk_level = "critical"
        reasons.append("high_risk_symptoms")
    
    # 2. 绝对数值阈值
    elif sbp >= 170 or dbp >= 105:
        risk_level = "high"
        reasons.append("threshold_violation")
        
    # 3. 个体稳态偏离 (基于稳态带)
    elif base_sbp:
        # 获取个体阈值，如果未生成(如数据不足)则回退到宽松的绝对值
        upper_limit = band.get("sbp_upper", base_sbp + 25)
        lower_limit = band.get("sbp_lower", base_sbp - 25)
        
        # 优先判断低灌注风险 (高基线 -> 低数值，属于高危)
        if base_sbp >= 150 and sbp <= 115:
            risk_level = "high"
            reasons.append("hypoperfusion_risk")
            
        # 判断是否突破稳态带
        elif sbp > upper_limit:
            # 突破上限：虽然未达 170，但对于该用户已显著异常 -> 中危/高危
            risk_level = "moderate" 
            reasons.append("baseline_deviation_up")
        elif sbp < lower_limit:
            # 突破下限
            risk_level = "moderate"
            reasons.append("baseline_deviation")
            
    # 4. 慢性高血压兜底
    if risk_level == "low":
        if base_sbp >= 160:
            risk_level = "moderate_high"
            reasons.append("chronic_high_base_critical")
        elif base_sbp >= 140:
            risk_level = "moderate"
            reasons.append("chronic_high_base")
            
    # 5. 中危症状兜底
    if risk_level == "low" and has_med_risk:
        risk_level = "moderate"
        reasons.append("med_risk_symptoms")

    # 6. 脉压差过大 (新增规则: > 60mmHg 提示动脉硬化风险)
    if risk_level == "low" and pp >= 60:
        risk_level = "moderate"
        reasons.append("widened_pulse_pressure")
        
    symptom_level = "high" if has_high_risk else ("medium" if has_med_risk else "none")
    
    return risk_level, reasons, symptom_level

def _calculate_scores(ctx, risk_level, symptom_level):
    """步骤3：计算评分"""
    base_sbp = ctx["base_sbp"]
    sbp_trend = ctx["sbp_trend"]
    
    # 1. 慢性张力: 基于基线 SBP
    chronic_tension = 0.1
    if base_sbp >= 160: chronic_tension = 0.9
    elif base_sbp >= 140: chronic_tension = 0.6
    elif base_sbp >= 130: chronic_tension = 0.4
    
    # 2. 急性推力: 基于趋势
    acute_push = 0.1
    if sbp_trend == "up": acute_push = 0.7
    elif sbp_trend == "down": acute_push = 0.2
    
    # 3. 总分
    score = (chronic_tension * 40) + (acute_push * 40)
    
    if symptom_level == "high":
        score += 50
    elif symptom_level == "medium":
        score += 20
        
    if risk_level == "critical":
        score += 20
        
    return chronic_tension, acute_push, int(score)

def _assess_plaque_risk(ctx, patterns):
    """
    评估血流动力学对动脉斑块的机械压力风险 (Hemodynamic Stress on Plaques)
    注意：这是基于物理参数的推断，非影像学诊断。
    """
    risk_score = 0.0
    reasons = []
    
    pp = ctx["pp"]
    sbp = ctx["sbp"]
    hr = ctx.get("hr", 70)
    
    # 1. 脉压差 (Pulsatile Stress) - 权重最高
    # 脉压大意味着血管硬化，脉搏波对斑块的冲击力大
    if pp >= 60:
        risk_score += 0.4
        reasons.append("high_pulse_pressure")
    elif pp >= 50:
        risk_score += 0.2
        
    # 2. 血压波动性 (Shear Stress Fluctuation)
    # 波动大造成机械疲劳
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
        
    # 归一化
    risk_score = min(1.0, risk_score)
    
    level = "low"
    if risk_score >= 0.7: level = "high"
    elif risk_score >= 0.4: level = "moderate"
    
    return {
        "score": risk_score,
        "level": level,
        "reasons": reasons
    }

def assess_risk_bundle(records, steady_data, events_by_segment, patterns=None):
    # 1. 安全检查
    if not records:
        # 即使没有记录，也应该返回默认的纵向状态和完整结构
        return {
            "acute_risk_level": "low",
            "symptom_level": "none",
            "total_score": 0,
            "chronic_tension": 0.0,
            "acute_push": 0.0,
            "plaque_risk": {},
            "longitudinal": calculate_lifecycle_state([]),
            "assessment_reasons": []
        }

    # 2. 提取上下文
    ctx = _extract_context(records, steady_data, events_by_segment)
    
    # 3. 判定风险等级
    risk_level, reasons, symptom_level = _evaluate_risk_level(ctx)

    # 4. 计算评分
    chronic_tension, acute_push, total_score = _calculate_scores(ctx, risk_level, symptom_level)

    # 5. 斑块稳定性风险评估 (独立维度)
    plaque_risk = _assess_plaque_risk(ctx, patterns)

    # 6. 纵向时间结构分析 (New)
    longitudinal = calculate_lifecycle_state(records)

    # 打印调试信息 (增强版，包含脉压和斑块风险)
    print(f"DEBUG_RISK >>> SBP:{ctx['sbp']} PP:{ctx['pp']} Risk:{risk_level} | Plaque:{plaque_risk.get('level')} | Stage:{longitudinal.get('stage')}")

    return {
        "acute_risk_level": risk_level,
        "assessment_reasons": reasons,
        "symptom_level": symptom_level,
        "chronic_tension": chronic_tension,
        "acute_push": acute_push,
        "plaque_risk": plaque_risk,
        "longitudinal": longitudinal,
        "total_score": total_score,
        "metrics": {
            "base_sbp": ctx.get("base_sbp"),
            "band": ctx.get("band"),
            "deviation": 0 # 占位
        }
    }