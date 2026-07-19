# -*- coding: utf-8 -*-
# binding_views.py
from flask import Blueprint, jsonify, request
import database
import json
from datetime import datetime
from engine.cardiovascular_engine import CardiovascularEngine

binding_bp = Blueprint('binding', __name__)

def parse_to_datetime_obj(ts):
    if isinstance(ts, datetime): return ts
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try: return datetime.strptime(ts, fmt)
            except ValueError: continue
    return datetime.now()

@binding_bp.route('/get_binding_status', methods=['GET'])
def get_binding_status():
    user_id = request.args.get('userId') or request.args.get('user_id')
    if not user_id:
        return jsonify({"code": 1, "msg": "Missing userId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()   # ★ 新增

    has_family_binding = False
    family_patients = []
    family_alert_risk = "none"
    family_patient_name = ""

    has_doctor_binding = False
    doctor_patients = []
    doctor_alert_count = 0

    try:
        # ★ 改：跨库获取表结构
        columns = database.get_table_columns(cursor, 'family_bindings')

        family_bonds = []
        if columns:
            target_col = "sharer_id" if "sharer_id" in columns else ("user_id" if "user_id" in columns else columns[1])
            cursor.execute(f"SELECT * FROM family_bindings WHERE {target_col} = {ph}", (user_id,))  # ★ 改
            family_bonds = cursor.fetchall()

        if family_bonds:
            has_family_binding = True
            family_patient_name = "我的关联被监护家人"
            p_id_holder = family_bonds[0]["patient_id"] if "patient_id" in columns else user_id

            family_patients.append({
                "patientId": p_id_holder,
                "patientName": family_patient_name
            })
            family_alert_risk = _calculate_realtime_risk(conn, cursor, p_id_holder)

        cursor.execute(f"SELECT * FROM doctor_bindings WHERE doctor_id = {ph}", (user_id,))  # ★ 改
        doctor_bonds = cursor.fetchall()

        if doctor_bonds:
            has_doctor_binding = True
            for bond in doctor_bonds:
                p_id = bond['patient_id']
                cursor.execute(f"SELECT name FROM users WHERE id = {ph}", (p_id,))  # ★ 改
                p_user = cursor.fetchone()
                p_name = p_user['name'] if p_user else "签约患者"

                doctor_patients.append({"patientId": p_id, "patientName": p_name})
                if _calculate_realtime_risk(conn, cursor, p_id) in ["high", "critical"]:
                    doctor_alert_count += 1

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "hasFamilyBinding": has_family_binding,
                "familyPatients": family_patients,
                "hasDoctorBinding": has_doctor_binding,
                "doctorPatients": doctor_patients,
                "familyAlertRisk": family_alert_risk,
                "doctorAlertCount": doctor_alert_count,
                "familyAlertSummary": {"patientName": family_patient_name}
            }
        })

    except Exception as e:
        print(f"⚠️ [Binding status proxy auto sync active]: {e}")
        return jsonify({
            "code": 0, "msg": "degraded success",
            "data": {
                "hasFamilyBinding": False, "familyPatients": [],
                "hasDoctorBinding": False, "doctorPatients": [],
                "familyAlertRisk": "none", "doctorAlertCount": 0, "familyAlertSummary": {"patientName": ""}
            }
        })


def _calculate_realtime_risk(conn, cursor, user_id):
    ph = database.get_placeholder()   # ★ 新增
    try:
        cursor.execute(
            f"SELECT sbp, dbp, hr, symptoms, datetime FROM measurements WHERE user_id = {ph} ORDER BY datetime DESC LIMIT 20",
            (user_id,)
        )  # ★ 改
        rows = cursor.fetchall()
        if not rows: return "none"

        records = []
        for r in rows:
            d_r = dict(r)
            try:
                if isinstance(d_r.get('symptoms'), str):
                    d_r['symptoms'] = json.loads(d_r['symptoms'] or '[]')
            except: d_r['symptoms'] = []
            d_r['datetime'] = parse_to_datetime_obj(d_r.get('datetime'))
            records.append(d_r)

        if len(records) < 2:
            return records[0].get("risk_level", "low")

        engine = CardiovascularEngine(history=records[1:], current=records[0])
        res = engine.run_all_diagnostics()
        return res.get("risk_level", "low")
    except:
        return "low"


@binding_bp.route('/register_user', methods=['POST'])
def register_user():
    try:
        data = request.json or {}
        user_id = data.get('user_id') or data.get('userId')
        name = data.get('name')
        age = data.get('age', 0)
        gender = data.get('gender', '')
        role = data.get('role', 'user')

        if not user_id or not name:
            return jsonify({"code": -1, "msg": "核心字段缺失，大脑拒绝写入"}), 400

        conn = database.get_db()
        cursor = conn.cursor()
        ph = database.get_placeholder()   # ★ 新增

        cursor.execute(f"SELECT id FROM users WHERE user_id = {ph}", (user_id,))  # ★ 改
        exists = cursor.fetchone()

        if exists:
            cursor.execute(f"""
                UPDATE users SET name={ph}, age={ph}, gender={ph}, role={ph} WHERE user_id={ph}
            """, (name, age, gender, role, user_id))  # ★ 改
        else:
            cursor.execute(f"""
                INSERT INTO users (user_id, name, age, gender, role) 
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
            """, (user_id, name, age, gender, role))  # ★ 改

        conn.commit()
        print(f"🟢 [DB] 用户 {name}({user_id}) 注册数据成功写入！", flush=True)

        return jsonify({"code": 0, "msg": "注册成功"}), 200

    except Exception as e:
        print(f"❌ [DB] 注册存盘发生坍塌: {str(e)}", flush=True)
        return jsonify({"code": 500, "msg": f"大脑数据库写入异常: {str(e)}"}), 500