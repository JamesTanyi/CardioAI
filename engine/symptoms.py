# app/engine/symptoms.py
"""
症状输入模块（语音 + 按钮）
输出结构化症状，用于 risk_level.py
"""

from typing import List, Dict


# ==========================
# 1. 症状关键词库
# ==========================

SYMPTOM_KEYWORDS = {
    "chest_pain": ["胸痛", "心口痛", "胸部剧痛"],
    "chest_tightness": ["胸闷", "憋气"],
    "dizzy": ["头晕", "发晕"],
    "severe_headache": ["剧烈头痛", "爆炸样头痛"],
    "thunderclap_headache": ["雷击样头痛", "突然剧痛"],
    "weakness_one_side": ["偏瘫", "一侧无力", "手脚没劲"],
    "slurred_speech": ["说话不清", "口齿不清"],
    "vision_loss": ["看不清", "视物模糊", "视力下降"],
    "short_breath": ["呼吸困难", "喘不上气"],
    "palpitations": ["心悸", "心跳快"],
    "fatigue": ["乏力", "没劲"],
    "general_discomfort": ["不舒服", "不适"],
    "anxiety": ["焦虑", "紧张"],
}


# ==========================
# 2. 语音文本解析
# ==========================

def parse_voice_text(text: str) -> List[str]:
    """
    输入：语音识别后的文本
    输出：症状代码列表（如 ["dizzy", "chest_tightness"]）
    """
    if not text:
        return []

    text = text.strip()
    detected = []

    for code, keywords in SYMPTOM_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                detected.append(code)
                break

    return detected


# ==========================
# 3. 按钮输入（直接传入症状代码）
# ==========================

def parse_button_input(symptom_codes: List[str]) -> List[str]:
    """
    输入：按钮选择的症状代码
    输出：同样的症状代码列表
    """
    return symptom_codes or []


# ==========================
# 4. 合并症状来源
# ==========================

def merge_symptoms(voice_symptoms: List[str], button_symptoms: List[str]) -> List[str]:
    """
    合并语音 + 按钮输入，去重
    """
    return list(set(voice_symptoms + button_symptoms))


# ==========================
# 5. 症状按稳态段聚合（供 risk_level 使用）
# ==========================

def symptoms_to_segments(symptoms: List[str]):
    """
    risk_level 需要 events_by_segment[-1]
    我们简单返回一个只有一个 segment 的结构：
    [
        { "symptoms": ["dizzy", "chest_tightness"] }
    ]
    """
    if not symptoms:
        return [{}]

    return [
        {sym: 1 for sym in symptoms}
    ]
# app/engine/symptoms.py

def analyze_symptoms(symptoms_list):
    """
    简单占位：根据症状列表返回一个 summary。
    你可以以后改成更复杂的规则。
    """
    if not symptoms_list:
        return {"summary": "未报告明显不适。"}

    return {"summary": "报告了不适症状，请结合血压情况留意变化。"}
