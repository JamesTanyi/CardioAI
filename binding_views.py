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
    """对应前端 app.js 启动和轮询调用"""
    user_id = request.args.get('userId') or request.args.get('user_id')
    if not user_id:
        return jsonify({"code": 1, "msg": "Missing userId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    has_family_binding = False
    family_patients = []
    family_alert_risk = "none"
    family_patient_name = ""

    has_doctor_binding = False
    doctor_patients = []
    doctor_alert_count = 0

    try:
        # 自适应探测 family_bindings 表结构，100% 防止 no such column
        columns = database.get_table_columns(cursor, 'family_bindings')

        family_bonds = []
        if columns:
            target_col = "sharer_id" if "sharer_id" in columns else ("user_id" if "user_id" in columns else columns[1])
            cursor.execute(f"SELECT * FROM family_bindings WHERE {target_col} = {ph}", (user_id,))
            family_bonds = cursor.fetchall()

        if family_bonds:
            has_family_binding = True
            p_id_holder = family_bonds[0]["patient_id"] if "patient_id" in columns else user_id

            # ★ 新增：查患者的 name + birth_date，拼成"姓名(出生日期)"展示名，
            #   方便家属一眼认出这是谁，而不是只看到一串内部 user_id
            cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (p_id_holder,))
            p_user = cursor.fetchone()
            if p_user and p_user.get('name'):
                bdate = p_user.get('birth_date') or ''
                family_patient_name = f"{p_user['name']}({bdate})" if bdate else p_user['name']
            else:
                family_patient_name = "我的关联被监护家人"  # 兜底：查不到患者资料时的老文案

            family_patients.append({
                "patientId": p_id_holder,
                "patientName": family_patient_name
            })
            # 💡 动态健康监控：抽取时间序列为家属端运算当前警报级别
            family_alert_risk = _calculate_realtime_risk(conn, cursor, p_id_holder)

        # 检查医生监护池
        cursor.execute(f"SELECT * FROM doctor_bindings WHERE doctor_id = {ph}", (user_id,))
        doctor_bonds = cursor.fetchall()

        if doctor_bonds:
            has_doctor_binding = True
            for bond in doctor_bonds:
                p_id = bond['patient_id']
                # ★ 改：同时查 birth_date，拼成展示名
                cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (p_id,))
                p_user = cursor.fetchone()
                if p_user and p_user.get('name'):
                    bdate = p_user.get('birth_date') or ''
                    p_name = f"{p_user['name']}({bdate})" if bdate else p_user['name']
                else:
                    p_name = "签约患者"  # 兜底：查不到患者资料时的老文案

                doctor_patients.append({"patientId": p_id, "patientName": p_name})
                # 如果医生监护的某位患者触发了高风险，医生的未读红点加1
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
    """辅助长效健康闭环：时序数据清洗并唤醒核心引擎"""
    ph = database.get_placeholder()
    try:
        cursor.execute(
            f"SELECT sbp, dbp, hr, symptoms, datetime FROM measurements WHERE user_id = {ph} ORDER BY datetime DESC LIMIT 20",
            (user_id,)
        )
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

@binding_bp.route('/get_feedback', methods=['GET'])
def get_feedback():
    return jsonify({"code": 0, "msg": "success", "data": {"feedbacks": []}})

@binding_bp.route('/register_user', methods=['POST'])
def register_user():
    """真正的核心大脑：将前端皮囊上报的用户数据，写入数据库"""
    try:
        data = request.json or {}
        user_id = data.get('user_id') or data.get('userId')  # 双重保险兼容字段
        name = data.get('name')
        age = data.get('age', 0)
        gender = data.get('gender', '')
        role = data.get('role', 'user')
        # ★ 新增：出生日期，注册时必填（前端已校验），用于家属/医生端展示"姓名(出生日期)"识别患者
        birth_date = data.get('birth_date') or data.get('birthDate') or ''

        if not user_id or not name:
            return jsonify({"code": -1, "msg": "核心字段缺失，大脑拒绝写入"}), 400

        conn = database.get_db()
        cursor = conn.cursor()
        ph = database.get_placeholder()

        # 检查是否已经是老用户，防止 UNIQUE 冲突
        cursor.execute(f"SELECT id FROM users WHERE user_id = {ph}", (user_id,))
        exists = cursor.fetchone()

        if exists:
            # 已存在则更新资料
            cursor.execute(f"""
                UPDATE users SET name={ph}, age={ph}, gender={ph}, role={ph}, birth_date={ph} WHERE user_id={ph}
            """, (name, age, gender, role, birth_date, user_id))
        else:
            # 新用户插入 users 表
            cursor.execute(f"""
                INSERT INTO users (user_id, name, age, gender, role, birth_date) 
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """, (user_id, name, age, gender, role, birth_date))

        conn.commit()
        print(f"🟢 [DB] 用户 {name}({user_id}) 注册数据成功写入！", flush=True)

        return jsonify({
            "code": 0,
            "msg": "注册成功"
        }), 200

    except Exception as e:
        print(f"❌ [DB] 注册存盘发生坍塌: {str(e)}", flush=True)
        return jsonify({"code": 500, "msg": f"大脑数据库写入异常: {str(e)}"}), 500