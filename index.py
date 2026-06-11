# -*- coding: utf8 -*-
import sys
import os
import json
from flask import Flask, request, jsonify

# 将当前目录加入系统路径
sys.path.append(os.path.dirname(__file__))

from engine.risk_level import assess_risk_bundle
from engine.emergency import analyze_emergency
from engine.language import generate_language_blocks
from engine.lifecycle import calculate_lifecycle_state

app = Flask(__name__)

@app.route('/', methods=['POST'])
def main():
    try:
        data = request.get_json() or {}

        symptoms = data.get('symptoms', [])
        vital_signs = data.get('vital_signs', {})

        # 构造 records（risk_level 和 emergency 都需要）
        record = {
            "symptoms": symptoms,
            "events": symptoms,
            "sbp": vital_signs.get("sbp"),
            "dbp": vital_signs.get("dbp"),
            "hr": vital_signs.get("hr"),
            "datetime": "now"
        }
        records = [record]

        # risk_level 所需结构
        steady_data = {}
        events_by_segment = []
        patterns = {}

        # 1) 风险评估
        risk_bundle = assess_risk_bundle(records, steady_data, events_by_segment, patterns)

        # 2) 急性动力学信号
        emergency_info = analyze_emergency(records, steady_data)

        # 3) 生成语言输出（方案 A）
        language_blocks = generate_language_blocks(records, steady_data, risk_bundle, {})

        return jsonify({
            "code": 0,
            "data": {
                "risk": risk_bundle,
                "emergency": emergency_info,
                "language": language_blocks
            }
        })

    except Exception as e:
        return jsonify({
            "code": -1,
            "message": str(e)
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
