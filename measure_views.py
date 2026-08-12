# -*- coding: utf-8 -*-
# measure_views.py
from flask import Blueprint, jsonify, request
import database
import json
from datetime import datetime

# 导入核心大脑
from engine.cardiovascular_engine import CardiovascularEngine

measure_bp = Blueprint('measure', __name__)

def parse_to_datetime_obj(ts):
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError: continue
    return datetime.now()

@measure_bp.route('/analyze', methods=['POST'])
def analyze_measurement():
    """对应前端 cloudService.analyze(data) -> POST /api/analyze"""
    req_data = request.json or {}
    user_id = req_data.get('userId') or req_data.get('user_id')
    sbp = req_data.get('sbp')
    dbp = req_data.get('dbp')
    hr = req_data.get('hr', 75)
    symptoms = req_data.get('symptoms', [])

    if not user_id or sbp is None or dbp is None:
        return jsonify({"code": 1, "msg": "缺失核心血压或用户ID"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()   # ★ 新增

    try:
        cursor.execute(f"""
            SELECT sbp, dbp, hr, symptoms, datetime 
            FROM measurements 
            WHERE user_id = {ph} 
            ORDER BY datetime DESC LIMIT 100
        """, (user_id,))  # ★ 改
        history_rows = cursor.fetchall()

        history_list = []
        for row in history_rows:
            rec = dict(row)
            try:
                if isinstance(rec.get('symptoms'), str):
                    rec['symptoms'] = json.loads(rec['symptoms'] or '[]')
            except:
                rec['symptoms'] = []
            rec['datetime'] = parse_to_datetime_obj(rec.get('datetime'))
            history_list.append(rec)

        # ★ 新增：查一下这个患者注册时填写的既往病史，传给引擎供Path B
        # 判定敏感度调整用(有高危心血管病史的人阈值更容易触发就医建议)。
        # 查询失败/字段为空都不影响主流程，兜底成空列表。
        health_history_list = []
        try:
            cursor.execute(f"SELECT health_history FROM users WHERE user_id = {ph}", (user_id,))
            user_row = cursor.fetchone()
            if user_row:
                raw_hh = dict(user_row).get('health_history')
                if raw_hh:
                    health_history_list = json.loads(raw_hh)
        except Exception as hh_err:
            print(f"⚠️ 读取health_history失败(不影响主流程): {hh_err}", flush=True)
            health_history_list = []

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        current_record = {
            "user_id": user_id,
            "sbp": int(sbp),
            "dbp": int(dbp),
            "hr": int(hr),
            "symptoms": symptoms if isinstance(symptoms, list) else [],
            "datetime": parse_to_datetime_obj(now_str)
        }

        engine = CardiovascularEngine(history=history_list, current=current_record, health_history=health_history_list)
        engine_res = engine.run_all_diagnostics()

        risk_level = engine_res.get("risk_level", "normal")
        user_msg = engine_res.get("message", "分析完成")
        details = engine_res.get("details", {})

        cursor.execute(f"""
            INSERT INTO measurements (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (
            user_id, int(sbp), int(dbp), int(hr),
            json.dumps(symptoms, ensure_ascii=False),
            risk_level, user_msg,
            json.dumps(details.get("reports", {}), ensure_ascii=False),
            now_str
        ))  # ★ 改
        conn.commit()

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "riskLevel": risk_level,
                "message": user_msg,
                "reports": details.get("reports", {}),
                "timeline": details.get("timeline", [])
            }
        })

    except Exception as e:
        print(f"❌ [Flask Analyze Endpoint Error]: {e}")
        return jsonify({"code": 500, "msg": f"核心引擎运行或数据存盘失败: {str(e)}"}), 500