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

                # ★ 改：把风险等级也一起返回，供医生端列表展示状态徽章 + 排序依据
                risk = _calculate_realtime_risk(conn, cursor, p_id)
                doctor_patients.append({"patientId": p_id, "patientName": p_name, "riskLevel": risk})
                # 如果医生监护的某位患者触发了高风险，医生的未读红点加1
                if risk in ["high", "critical"]:
                    doctor_alert_count += 1

            # ★ 新增：按病情严重程度排序，最需要关注的患者排在列表最前面（预警优先展示）
            #   闭环理念：医生端不是"有病来找",而是持续追踪，列表顺序本身就是一种预警
            risk_priority = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "none": 0}
            doctor_patients.sort(key=lambda p: risk_priority.get(p["riskLevel"], 0), reverse=True)

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


# ============================================================
# ★ 新增：V10 邀请绑定主链路（永久链接模式）
# 前端 intro.js 里调用的 cloudService.validateInvite / bindByInvite
# 对应的后端实现，此前完全缺失，导致邀请绑定功能实际不可用。
# 分享链接里携带的是患者的 user_id 本身（永久有效），不是一次性 token。
# ============================================================

@binding_bp.route('/validate_invite', methods=['POST'])
def validate_invite():
    """
    邀请确认页打开时调用：校验链接里的 patientId 是否对应真实存在的患者，
    并返回患者展示名 + 一份简单摘要，供家属/医生确认"这是不是我要绑定的人"。
    """
    data = request.json or {}
    patient_id = data.get('patientId')
    role = data.get('role')  # 'family' | 'doctor'，当前校验逻辑不区分角色，仅透传保留

    if not patient_id:
        return jsonify({"code": 1, "msg": "缺少 patientId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (patient_id,))
        patient = cursor.fetchone()

        if not patient or not patient.get('name'):
            return jsonify({"code": -1, "msg": "邀请链接无效或患者不存在"}), 404

        bdate = patient.get('birth_date') or ''
        patient_name = f"{patient['name']}({bdate})" if bdate else patient['name']

        # 患者摘要：取最近一次测量记录，给确认页一个基本的"认人"参考
        cursor.execute(
            f"SELECT sbp, dbp, risk_level, datetime FROM measurements WHERE user_id = {ph} ORDER BY datetime DESC LIMIT 1",
            (patient_id,)
        )
        latest = cursor.fetchone()
        patient_summary = {
            "name": patient_name,
            "latestSbp": latest['sbp'] if latest else None,
            "latestDbp": latest['dbp'] if latest else None,
            "latestRiskLevel": latest['risk_level'] if latest else None,
            "latestDatetime": latest['datetime'] if latest else None,
        }

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "patientName": patient_name,
                "patientSummary": patient_summary
            }
        })

    except Exception as e:
        print(f"❌ [validate_invite] 校验失败: {e}", flush=True)
        return jsonify({"code": -1, "msg": f"校验失败: {str(e)}"}), 500


@binding_bp.route('/bind_by_invite', methods=['POST'])
def bind_by_invite():
    """
    用户点击"确认绑定"后调用：写入 family_bindings 或 doctor_bindings。
    如果之前已经绑定过同一对 (viewer, patient)，则把状态刷新为 active，
    不会因为 UNIQUE 约束报错而失败（幂等处理，允许重复点击/重新绑定）。
    """
    data = request.json or {}
    patient_id = data.get('patientId')
    role = data.get('role')
    viewer_id = data.get('viewerId')
    viewer_name = data.get('viewerName') or ''
    hospital = data.get('hospital') or ''
    department = data.get('department') or ''

    if not patient_id or not role or not viewer_id:
        return jsonify({"code": -1, "msg": "缺少必要参数"}), 400
    if role not in ('family', 'doctor'):
        return jsonify({"code": -1, "msg": "role 参数不合法"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        # 再次确认患者存在（防止确认页打开后患者数据被删除的边界情况）
        cursor.execute(f"SELECT name FROM users WHERE user_id = {ph}", (patient_id,))
        patient = cursor.fetchone()
        if not patient:
            return jsonify({"code": -1, "msg": "患者不存在，绑定失败"}), 404
        patient_name = patient.get('name') or ''

        # 确保家属/医生本人也在 users 表里有记录，避免后续查询缺数据
        cursor.execute(f"SELECT id FROM users WHERE user_id = {ph}", (viewer_id,))
        viewer_exists = cursor.fetchone()
        if not viewer_exists:
            cursor.execute(
                f"INSERT INTO users (user_id, name, role) VALUES ({ph}, {ph}, {ph})",
                (viewer_id, viewer_name, role)
            )

        if role == 'family':
            cursor.execute(
                f"SELECT id FROM family_bindings WHERE family_id={ph} AND patient_id={ph}",
                (viewer_id, patient_id)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    f"UPDATE family_bindings SET status='active', name={ph} WHERE family_id={ph} AND patient_id={ph}",
                    (patient_name, viewer_id, patient_id)
                )
            else:
                cursor.execute(
                    f"INSERT INTO family_bindings (family_id, patient_id, name, status) VALUES ({ph}, {ph}, {ph}, 'active')",
                    (viewer_id, patient_id, patient_name)
                )
        else:  # doctor
            cursor.execute(
                f"SELECT id FROM doctor_bindings WHERE doctor_id={ph} AND patient_id={ph}",
                (viewer_id, patient_id)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    f"""UPDATE doctor_bindings SET status='active', doctor_name={ph}, hospital={ph}, department={ph}
                        WHERE doctor_id={ph} AND patient_id={ph}""",
                    (viewer_name, hospital, department, viewer_id, patient_id)
                )
            else:
                cursor.execute(
                    f"""INSERT INTO doctor_bindings (doctor_id, patient_id, doctor_name, hospital, department, status)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, 'active')""",
                    (viewer_id, patient_id, viewer_name, hospital, department)
                )

        conn.commit()
        print(f"🟢 [DB] 绑定成功: {role} {viewer_id} -> patient {patient_id}", flush=True)

        return jsonify({"code": 0, "msg": "绑定成功"})

    except Exception as e:
        print(f"❌ [bind_by_invite] 绑定失败: {e}", flush=True)
        return jsonify({"code": -1, "msg": f"绑定失败: {str(e)}"}), 500