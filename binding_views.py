#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用户绑定、邀请、反馈相关的路由 (Views)
"""

import secrets
import random
import string
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

import database

# 创建一个名为 'binding' 的蓝图
binding_bp = Blueprint('binding_views', __name__)

# ──────────────────────────────────────────────
# /register_user  注册/更新用户信息
# ──────────────────────────────────────────────
@binding_bp.route("/register_user", methods=["POST"])
def register_user():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    user_id = data.get("userId", "").strip()
    name = data.get("name", "").strip()
    age = data.get("age", 0)
    gender = data.get("gender", "").strip()
    role = data.get("role", "user").strip()

    if not user_id:
        return jsonify({"error": "缺少 userId"}), 400
    if not name:
        return jsonify({"error": "缺少姓名"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 尝试插入，如果已存在则更新
        if USE_CLOUD_DB:
            cursor.execute("""
                INSERT INTO users (user_id, name, age, gender, role)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE name=%s, age=%s, gender=%s, role=%s
            """, (user_id, name, age, gender, role, name, age, gender, role))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO users (user_id, name, age, gender, role)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, name, age, gender, role))
        conn.commit()
        print(f"✅ [DB] 用户注册成功: {user_id} ({name}, {role})", flush=True)
        return jsonify({"code": 0, "message": "注册成功"})
    except Exception as e:
        return jsonify({"error": "注册失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /get_family_list  获取已绑定家人列表
# ──────────────────────────────────────────────
@binding_bp.route("/get_family_list", methods=["GET"])
def get_family_list():
    family_id = request.args.get("familyId")
    if not family_id:
        return jsonify({"error": "缺少 familyId 参数"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("""
                SELECT patient_id, name, created_at
                FROM family_bindings
                WHERE family_id = %s AND status='active'
                ORDER BY created_at DESC
            """, (family_id,))
        else:
            cursor.execute("""
                SELECT patient_id, name, created_at
                FROM family_bindings
                WHERE family_id = ? AND status='active'
                ORDER BY created_at DESC
            """, (family_id,))
        rows = cursor.fetchall()
        return jsonify({"code": 0, "data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /send_feedback  家属或医生发反馈给患者
# ──────────────────────────────────────────────
@binding_bp.route("/send_feedback", methods=["POST"])
def send_feedback():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    from_id   = data.get("fromId")
    from_role = data.get("fromRole", "family")
    to_id     = data.get("toId")
    content   = data.get("content", "").strip()

    if not all([from_id, to_id, content]):
        return jsonify({"error": "缺少 fromId / toId / content"}), 400
    if len(content) > 500:
        return jsonify({"error": "反馈内容不能超过500字"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 根据角色检查对应的绑定关系（仅 active）
        if from_role == "doctor":
            if USE_CLOUD_DB:
                cursor.execute(
                    "SELECT id FROM doctor_bindings WHERE doctor_id=%s AND patient_id=%s AND status='active'",
                    (from_id, to_id)
                )
            else:
                cursor.execute(
                    "SELECT id FROM doctor_bindings WHERE doctor_id=? AND patient_id=? AND status='active'",
                    (from_id, to_id)
                )
        else:
            if USE_CLOUD_DB:
                cursor.execute(
                    "SELECT id FROM family_bindings WHERE family_id=%s AND patient_id=%s AND status='active'",
                    (from_id, to_id)
                )
            else:
                cursor.execute(
                    "SELECT id FROM family_bindings WHERE family_id=? AND patient_id=? AND status='active'",
                    (from_id, to_id)
                )
        binding = cursor.fetchone()
        if not binding:
            return jsonify({"error": "未绑定该患者，无法发送反馈"}), 403

        if USE_CLOUD_DB:
            cursor.execute("""
                INSERT INTO feedbacks (from_id, from_role, to_id, content)
                VALUES (%s, %s, %s, %s)
            """, (from_id, from_role, to_id, content))
        else:
            cursor.execute("""
                INSERT INTO feedbacks (from_id, from_role, to_id, content)
                VALUES (?, ?, ?, ?)
            """, (from_id, from_role, to_id, content))
        conn.commit()
        print(f"💬 [DB] 反馈: {from_id}({from_role}) → {to_id}", flush=True)
        return jsonify({"code": 0, "message": "反馈已发送"})
    except Exception as e:
        return jsonify({"error": "发送失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /get_feedback  患者查看收到的反馈
# ──────────────────────────────────────────────
@binding_bp.route("/get_feedback", methods=["GET"])
def get_feedback():
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "缺少 userId 参数"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("""
                SELECT id, from_id, from_role, content, is_read, created_at
                FROM feedbacks
                WHERE to_id = %s
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT id, from_id, from_role, content, is_read, created_at
                FROM feedbacks
                WHERE to_id = ?
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))
        rows = cursor.fetchall()

        feedbacks = [dict(r) for r in rows]
        unread_count = sum(1 for f in feedbacks if f["is_read"] == 0)

        if USE_CLOUD_DB:
            cursor.execute(
                "UPDATE feedbacks SET is_read=1 WHERE to_id=%s AND is_read=0",
                (user_id,)
            )
        else:
            cursor.execute(
                "UPDATE feedbacks SET is_read=1 WHERE to_id=? AND is_read=0",
                (user_id,)
            )
        conn.commit()
        return jsonify({"code": 0, "data": feedbacks, "unread": unread_count})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v8 /confirm_binding  家属/医生确认绑定（pending → active）
# ──────────────────────────────────────────────
@binding_bp.route("/confirm_binding", methods=["POST"])
def confirm_binding():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    viewer_id = data.get("viewerId")  # 家属ID 或 医生ID
    patient_id = data.get("patientId")
    role = data.get("role", "family")  # 'family' 或 'doctor'
    token = (data.get("invite_token") or data.get("token") or "").strip()

    if not viewer_id:
        return jsonify({"error": "缺少 viewerId"}), 400

    # 如果提供了 invite token，则以 token 中的 patient_id 为准并验证 token
    token_row = None
    if token:
        conn = database.get_db()
        cursor = conn.cursor()
        USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
        try:
            if USE_CLOUD_DB:
                cursor.execute("SELECT * FROM invite_tokens WHERE token=%s", (token,))
            else:
                cursor.execute("SELECT * FROM invite_tokens WHERE token=?", (token,))
            token_row = cursor.fetchone()
            if not token_row:
                return jsonify({"error": "邀请 token 无效"}), 404
            token_row = dict(token_row) if isinstance(token_row, dict) or hasattr(token_row, 'keys') else dict(token_row)
            if token_row.get("used"):
                return jsonify({"error": "该邀请 token 已被使用"}), 400
            expires_str = token_row.get("expires_at")
            if expires_str:
                try:
                    expires_at = datetime.strptime(str(expires_str)[:19], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() > expires_at:
                        return jsonify({"error": "邀请 token 已过期，请联系患者重新发送"}), 400
                except Exception:
                    pass
            # 角色匹配
            if token_row.get("role") != role:
                return jsonify({"error": "此 token 与请求角色不匹配"}), 403
            # 以 token 中 patient_id 为准
            patient_id = token_row.get("patient_id")
        except Exception as e:
            return jsonify({"error": "验证 token 失败", "detail": str(e)}), 500

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if role == 'doctor':
            table = 'doctor_bindings'
            viewer_col = 'doctor_id'
        else:
            table = 'family_bindings'
            viewer_col = 'family_id'

        if USE_CLOUD_DB:
            cursor.execute(
                f"SELECT id, status FROM {table} WHERE {viewer_col}=%s AND patient_id=%s",
                (viewer_id, patient_id)
            )
        else:
            cursor.execute(
                f"SELECT id, status FROM {table} WHERE {viewer_col}=? AND patient_id=?",
                (viewer_id, patient_id)
            )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "未找到待确认的绑定关系"}), 404

        current_status = row["status"] if isinstance(row, dict) else row["status"] if hasattr(row, "status") else "pending"
        if current_status == 'active':
            return jsonify({"code": 0, "message": "绑定已确认", "status": "active"})

        if USE_CLOUD_DB:
            cursor.execute(
                f"UPDATE {table} SET status='active' WHERE {viewer_col}=%s AND patient_id=%s",
                (viewer_id, patient_id)
            )
        else:
            cursor.execute(
                f"UPDATE {table} SET status='active' WHERE {viewer_col}=? AND patient_id=?",
                (viewer_id, patient_id)
            )
        
        # ★★★ 关键修复：在确认绑定后，找到并标记邀请码为已使用 ★★★
        # 通过 used_by 字段反向查找是哪个邀请码触发了这个绑定
        if USE_CLOUD_DB:
            # 策略：一旦任何绑定被确认，就将该患者所有未使用的邀请码都标记为已用
            cursor.execute("UPDATE invite_codes SET used=1 WHERE patient_id=%s AND used=0", (patient_id,))
        else:
            # 策略：一旦任何绑定被确认，就将该患者所有未使用的邀请码都标记为已用
            cursor.execute(
                "UPDATE invite_codes SET used=1 WHERE patient_id=? AND used=0",
                (patient_id,)
            )
        conn.commit()

        # 如果是 token 驱动的确认，则标记 token 已用
        if token and token_row:
            try:
                if USE_CLOUD_DB:
                    cursor.execute("UPDATE invite_tokens SET used=1, used_by=%s WHERE token=%s", (viewer_id, token))
                else:
                    cursor.execute("UPDATE invite_tokens SET used=1, used_by=? WHERE token=?", (viewer_id, token))
                conn.commit()
            except Exception:
                pass

        print(f"✅ [DB] 绑定已确认: {viewer_id}({role}) → {patient_id}", flush=True)
        return jsonify({"code": 0, "message": "绑定已确认", "status": "active"})
    except Exception as e:
        return jsonify({"error": "确认失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v8 /reject_binding  家属/医生拒绝绑定（pending → rejected）
# ──────────────────────────────────────────────
@binding_bp.route("/reject_binding", methods=["POST"])
def reject_binding():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    viewer_id = data.get("viewerId")
    patient_id = data.get("patientId")
    role = data.get("role", "family")

    if not all([viewer_id, patient_id]):
        return jsonify({"error": "缺少 viewerId / patientId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if role == 'doctor':
            table = 'doctor_bindings'
            viewer_col = 'doctor_id'
        else:
            table = 'family_bindings'
            viewer_col = 'family_id'

        if USE_CLOUD_DB:
            cursor.execute(
                f"UPDATE {table} SET status='rejected' WHERE {viewer_col}=%s AND patient_id=%s AND status='pending'",
                (viewer_id, patient_id)
            )
        else:
            cursor.execute(
                f"UPDATE {table} SET status='rejected' WHERE {viewer_col}=? AND patient_id=? AND status='pending'",
                (viewer_id, patient_id)
            )
        conn.commit()
        print(f"❌ [DB] 绑定已拒绝: {viewer_id}({role}) → {patient_id}", flush=True)
        return jsonify({"code": 0, "message": "已拒绝绑定"})
    except Exception as e:
        return jsonify({"error": "操作失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v8 /get_patient_summary  获取患者摘要信息（确认绑定时展示）
# ──────────────────────────────────────────────
@binding_bp.route("/get_patient_summary", methods=["GET"])
def get_patient_summary():
    patient_id = request.args.get("patientId", "").strip()
    if not patient_id:
        return jsonify({"error": "缺少 patientId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 获取用户基本信息
        if USE_CLOUD_DB:
            cursor.execute("SELECT name, age, gender FROM users WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT name, age, gender FROM users WHERE user_id=?", (patient_id,))
        user = cursor.fetchone()

        # 获取最近一次测量
        if USE_CLOUD_DB:
            cursor.execute(
                "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=%s ORDER BY datetime DESC LIMIT 1",
                (patient_id,)
            )
        else:
            cursor.execute(
                "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=? ORDER BY datetime DESC LIMIT 1",
                (patient_id,)
            )
        latest = cursor.fetchone()

        # 获取总测量次数
        if USE_CLOUD_DB:
            cursor.execute("SELECT COUNT(*) as cnt FROM measurements WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT COUNT(*) as cnt FROM measurements WHERE user_id=?", (patient_id,))
        count_row = cursor.fetchone()

        result = {
            "patientId": patient_id,
            "name": user["name"] if user else "",
            "age": user["age"] if user else 0,
            "gender": user["gender"] if user else "",
            "totalMeasurements": count_row["cnt"] if count_row else 0,
            "latest": None
        }

        if latest:
            result["latest"] = {
                "sbp": latest["sbp"],
                "dbp": latest["dbp"],
                "hr": latest["hr"],
                "risk_level": latest["risk_level"],
                "datetime": str(latest["datetime"])[:16] if latest["datetime"] else ""
            }

        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v10 /validate_invite  验证患者邀请（无需 Token，永久有效）
# ──────────────────────────────────────────────
@binding_bp.route("/validate_invite", methods=["POST"])
def validate_invite():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    patient_id = data.get("patientId", "").strip()
    role = data.get("role", "family").strip()

    if not patient_id:
        return jsonify({"error": "缺少 patientId"}), 400
    if role not in ("family", "doctor"):
        return jsonify({"error": "role 必须是 family 或 doctor"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 验证患者存在
        if USE_CLOUD_DB:
            cursor.execute("SELECT name, age, gender FROM users WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT name, age, gender FROM users WHERE user_id=?", (patient_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "该患者不存在"}), 404

        # 获取最近一次测量
        if USE_CLOUD_DB:
            cursor.execute(
                "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=%s ORDER BY datetime DESC LIMIT 1",
                (patient_id,)
            )
        else:
            cursor.execute(
                "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=? ORDER BY datetime DESC LIMIT 1",
                (patient_id,)
            )
        latest = cursor.fetchone()

        # 获取总测量次数
        if USE_CLOUD_DB:
            cursor.execute("SELECT COUNT(*) as cnt FROM measurements WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT COUNT(*) as cnt FROM measurements WHERE user_id=?", (patient_id,))
        count_row = cursor.fetchone()

        patient_name = user["name"] if user else ""
        patient_info = {
            "name": patient_name,
            "age": user["age"] if user else 0,
            "gender": user["gender"] if user else "",
            "totalMeasurements": count_row["cnt"] if count_row else 0,
            "latest": None
        }
        if latest:
            patient_info["latest"] = {
                "sbp": latest["sbp"],
                "dbp": latest["dbp"],
                "hr": latest["hr"],
                "risk_level": latest["risk_level"],
                "datetime": str(latest["datetime"])[:16] if latest["datetime"] else ""
            }

        print(f"✅ [DB] 邀请验证成功: {patient_id} ({role})", flush=True)
        return jsonify({
            "code": 0,
            "data": {
                "patientId": patient_id,
                "patientName": patient_name,
                "role": role,
                "patientSummary": patient_info
            }
        })
    except Exception as e:
        return jsonify({"error": "验证失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v10 /bind_by_invite  通过患者ID直接绑定（无需 Token，永久有效）
# ──────────────────────────────────────────────
@binding_bp.route("/bind_by_invite", methods=["POST"])
def bind_by_invite():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400
    print(f"🔍 [DEBUG] bind_by_invite 收到: {data}", flush=True) 

    patient_id = data.get("patientId", "").strip()
    role = data.get("role", "family").strip()
    viewer_id = data.get("viewerId", "").strip()
    viewer_name = data.get("viewerName", "").strip()
    hospital = data.get("hospital", "").strip()
    department = data.get("department", "").strip()

    if not patient_id:
        return jsonify({"error": "缺少 patientId"}), 400
    if not viewer_id:
        return jsonify({"error": "缺少 viewerId"}), 400
    if role not in ("family", "doctor"):
        return jsonify({"error": "role 必须是 family 或 doctor"}), 400

    # 自绑定守卫
    if viewer_id == patient_id:
        return jsonify({"error": "不能绑定自己"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 验证患者存在
        if USE_CLOUD_DB:
            cursor.execute("SELECT id FROM users WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT id FROM users WHERE user_id=?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "该患者不存在"}), 404

        # 根据 role 选表
        if role == "doctor":
            table = "doctor_bindings"
            viewer_col = "doctor_id"
            viewer_name_col = "doctor_name"
        else:
            table = "family_bindings"
            viewer_col = "family_id"
            viewer_name_col = "name"

        # 查询现有绑定（幂等处理）
        if USE_CLOUD_DB:
            cursor.execute(
                f"SELECT status FROM {table} WHERE {viewer_col}=%s AND patient_id=%s",
                (viewer_id, patient_id)
            )
        else:
            cursor.execute(
                f"SELECT status FROM {table} WHERE {viewer_col}=? AND patient_id=?",
                (viewer_id, patient_id)
            )
        existing = cursor.fetchone()
        existing_status = existing["status"] if existing else None

        if existing_status == "active":
            # 已绑定 → 幂等返回
            conn.commit()
            return jsonify({
                "code": 0,
                "status": "active",
                "message": "已绑定（无需重复操作）",
                "patientId": patient_id,
                "role": role
            })

        # 一步写入 active（INSERT 或 UPDATE，不走 pending）
        if existing:
            # 更新现有记录为 active
            if role == "doctor":
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=%s, hospital=%s, department=%s, status='active' WHERE {viewer_col}=%s AND patient_id=%s",
                        (viewer_name or "医生", hospital, department, viewer_id, patient_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=?, hospital=?, department=?, status='active' WHERE {viewer_col}=? AND patient_id=?",
                        (viewer_name or "医生", hospital, department, viewer_id, patient_id)
                    )
            else:
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=%s, status='active' WHERE {viewer_col}=%s AND patient_id=%s",
                        (viewer_name or "家人", viewer_id, patient_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=?, status='active' WHERE {viewer_col}=? AND patient_id=?",
                        (viewer_name or "家人", viewer_id, patient_id)
                    )
        else:
            # 新建绑定
            if role == "doctor":
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"INSERT INTO {table} (doctor_id, patient_id, doctor_name, hospital, department, status) VALUES (%s, %s, %s, %s, %s, 'active')",
                        (viewer_id, patient_id, viewer_name or "医生", hospital, department)
                    )
                else:
                    cursor.execute(
                        f"INSERT INTO {table} (doctor_id, patient_id, doctor_name, hospital, department, status) VALUES (?, ?, ?, ?, ?, 'active')",
                        (viewer_id, patient_id, viewer_name or "医生", hospital, department)
                    )
            else:
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"INSERT INTO {table} (family_id, patient_id, name, status) VALUES (%s, %s, %s, 'active')",
                        (viewer_id, patient_id, viewer_name or "家人")
                    )
                else:
                    cursor.execute(
                        f"INSERT INTO {table} (family_id, patient_id, name, status) VALUES (?, ?, ?, 'active')",
                        (viewer_id, patient_id, viewer_name or "家人")
                    )

        conn.commit()
        print(f"✅ [DB] 邀请绑定成功: {viewer_id} → 患者 {patient_id} ({role})", flush=True)
        return jsonify({
            "code": 0,
            "status": "active",
            "message": "绑定成功",
            "patientId": patient_id,
            "role": role
        })
    except Exception as e:
        return jsonify({"error": "绑定失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /generate_invite_code  患者生成邀请码（用于医生/家人绑定）
# ──────────────────────────────────────────────
@binding_bp.route("/generate_invite_code", methods=["POST"])
def generate_invite_code():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    patient_id = data.get("patientId") or data.get("user_id")
    if not patient_id:
        return jsonify({"error": "缺少 patientId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 生成 6 位随机数字
        code = ''.join(random.choices(string.digits, k=6))

        if USE_CLOUD_DB:
            cursor.execute("""
                INSERT INTO invite_codes (code, patient_id, expires_at)
                VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 24 HOUR))
            """, (code, patient_id))
        else:
            cursor.execute("""
                INSERT INTO invite_codes (code, patient_id, expires_at)
                VALUES (?, ?, datetime('now', '+24 hours'))
            """, (code, patient_id))
        conn.commit()
        print(f"📨 [DB] 生成邀请码: {code} → {patient_id}", flush=True)
        return jsonify({"code": 0, "data": {"inviteCode": code, "expiresIn": "24小时"}})
    except Exception as e:
        return jsonify({"error": "生成失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v11 /bind_by_code  通过邀请码通用绑定（支持医生/家属）
# ──────────────────────────────────────────────
@binding_bp.route("/bind_by_code", methods=["POST"])
def bind_by_code():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    invite_code = data.get("code", "").strip()
    # 1. 使用通用参数
    role        = data.get("role", "doctor").strip()
    viewer_id   = data.get("viewerId") or data.get("doctorId") # 兼容旧的 doctorId
    viewer_name = data.get("viewerName") or data.get("doctorName") or data.get("name") # 兼容旧的 doctorName
    hospital    = data.get("hospital", "")
    department  = data.get("department", "")

    if not invite_code or not viewer_id:
        return jsonify({"error": "缺少 code / viewerId"}), 400
    if len(invite_code) != 6 or not invite_code.isdigit():
        return jsonify({"error": "邀请码格式不正确，应为6位数字"}), 400
    if role not in ('doctor', 'family'):
        return jsonify({"error": "role 必须是 'doctor' 或 'family'"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 2. 验证邀请码
        if USE_CLOUD_DB:
            cursor.execute(
                "SELECT * FROM invite_codes WHERE code=%s",
                (invite_code,)
            )
        else:
            cursor.execute("SELECT * FROM invite_codes WHERE code=?", (invite_code,))
        
        code_row = cursor.fetchone()
        if not code_row:
            return jsonify({"error": "邀请码不存在"}), 404

        code_row = dict(code_row)
        if code_row.get("used"):
            return jsonify({"error": "邀请码已被使用"}), 400

        expires_str = code_row.get("expires_at")
        if expires_str:
            from datetime import datetime as dt
            # 兼容 MySQL 和 SQLite 的日期格式
            try:
                expires_at = dt.strptime(str(expires_str)[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expires_at = dt.strptime(str(expires_str)[:19], "%Y-%m-%d %H:%M:%S.%f")
            if dt.now() > expires_at:
                return jsonify({"error": "邀请码已过期，请重新生成"}), 400

        patient_id = code_row["patient_id"]

        if viewer_id == patient_id:
            return jsonify({"error": "不能绑定自己"}), 400

        # 3. 根据角色选择表和字段
        if role == 'doctor':
            table = 'doctor_bindings'
            viewer_col = 'doctor_id'
            viewer_name_col = 'doctor_name'
            default_name = '医生'
        else: # family
            table = 'family_bindings'
            viewer_col = 'family_id'
            viewer_name_col = 'name'
            default_name = '家人'

        # 4. 检查是否已存在 active 绑定
        if USE_CLOUD_DB:
            cursor.execute(f"SELECT status FROM {table} WHERE {viewer_col}=%s AND patient_id=%s", (viewer_id, patient_id))
        else:
            cursor.execute(f"SELECT status FROM {table} WHERE {viewer_col}=? AND patient_id=?", (viewer_id, patient_id))
        
        existing = cursor.fetchone()
        if existing and existing['status'] == 'active':
            return jsonify({"code": 0, "message": "绑定已存在", "status": "active"})

        # 5. 写入绑定表（pending状态），并标记邀请码已使用
        # 使用 UPSERT (INSERT ... ON DUPLICATE KEY UPDATE) 或分步更新逻辑
        if existing: # 更新为 pending
            if role == 'doctor':
                sql = f"UPDATE {table} SET {viewer_name_col}=%s, hospital=%s, department=%s, status='pending' WHERE {viewer_col}=%s AND patient_id=%s"
                params = (viewer_name or default_name, hospital, department, viewer_id, patient_id)
            else:
                sql = f"UPDATE {table} SET {viewer_name_col}=%s, status='pending' WHERE {viewer_col}=%s AND patient_id=%s"
                params = (viewer_name or default_name, viewer_id, patient_id)
        else: # 插入新记录
            if role == 'doctor':
                sql = f"INSERT INTO {table} ({viewer_col}, patient_id, {viewer_name_col}, hospital, department, status) VALUES (%s, %s, %s, %s, %s, 'pending')"
                params = (viewer_id, patient_id, viewer_name or default_name, hospital, department)
            else:
                sql = f"INSERT INTO {table} ({viewer_col}, patient_id, {viewer_name_col}, status) VALUES (%s, %s, %s, 'pending')"
                params = (viewer_id, patient_id, viewer_name or default_name)

        if not USE_CLOUD_DB:
            sql = sql.replace('%s', '?')
        
        cursor.execute(sql, params)

        conn.commit()
        print(f"📨 [DB] {role}通过邀请码绑定(pending): {viewer_id} → {patient_id} (code: {invite_code})", flush=True)
        return jsonify({"code": 0, "message": "绑定已提交，等待确认", "status": "pending", "patientId": patient_id, "patientName": code_row.get("patient_id", "")})
    except Exception as e:
        return jsonify({"error": "绑定失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /bind_doctor_by_code (兼容旧版)
# ──────────────────────────────────────────────
@binding_bp.route("/bind_doctor_by_code", methods=["POST"])
def bind_doctor_by_code():
    # 这是一个代理，将旧请求转发到新接口
    # 确保请求体中的 doctorId, doctorName 等字段能被新接口正确解析
    return bind_by_code()

# ──────────────────────────────────────────────
# /get_doctor_patients  医生查看已绑定患者
# ──────────────────────────────────────────────
@binding_bp.route("/get_doctor_patients", methods=["GET"])
def get_doctor_patients():
    doctor_id = request.args.get("doctorId")
    if not doctor_id:
        return jsonify({"error": "缺少 doctorId 参数"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("""
                SELECT patient_id, doctor_name, hospital, department, created_at
                FROM doctor_bindings
                WHERE doctor_id = %s AND status='active'
                ORDER BY created_at DESC
            """, (doctor_id,))
        else:
            cursor.execute("""
                SELECT patient_id, doctor_name, hospital, department, created_at
                FROM doctor_bindings
                WHERE doctor_id = ? AND status='active'
                ORDER BY created_at DESC
            """, (doctor_id,))
        rows = cursor.fetchall()
        return jsonify({"code": 0, "data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /get_family_patient  家属查找绑定的患者
# ──────────────────────────────────────────────
@binding_bp.route("/get_family_patient", methods=["GET"])
def get_family_patient():
    viewer_id = request.args.get("viewerId", "").strip()
    if not viewer_id:
        return jsonify({"error": "缺少 viewerId 参数"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("""
                SELECT patient_id, name, created_at
                FROM family_bindings
                WHERE family_id = %s AND status='active'
                ORDER BY created_at DESC
                LIMIT 1
            """, (viewer_id,))
        else:
            cursor.execute("""
                SELECT patient_id, name, created_at
                FROM family_bindings
                WHERE family_id = ? AND status='active'
                ORDER BY created_at DESC
                LIMIT 1
            """, (viewer_id,))
        row = cursor.fetchone()
        if row:
            name_val = row["name"] if "name" in row.keys() else (row["patient_id"] or "")
            return jsonify({
                "code": 0,
                "patientId": row["patient_id"],
                "patientName": name_val or row["patient_id"],
                "relation": name_val or "家人"
            })
        else:
            return jsonify({"code": 0, "patientId": "", "patientName": "", "message": "未找到绑定"})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /get_binding_status  检查用户绑定状态 + 预警摘要（APP式启动接口）
# ──────────────────────────────────────────────
@binding_bp.route("/get_binding_status", methods=["GET"])
def get_binding_status():
    user_id = request.args.get("userId", "").strip()
    # 1. 引入分页参数
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("pageSize", 10))
        if page < 1: page = 1
        if page_size < 1 or page_size > 100: page_size = 10 # 每页最多100条
    except ValueError:
        page = 1
        page_size = 10
    offset = (page - 1) * page_size

    if not user_id:
        return jsonify({"error": "缺少 userId 参数"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        result = {
            "hasFamilyBinding": False,
            "hasDoctorBinding": False,
            "familyPatients": [],
            "doctorPatients": [],
            "familyAlertRisk": "none",
            "doctorAlertCount": 0,
            "familyAlertSummary": None,
            "doctorAlertSummary": None,
            # 2. 添加分页信息到返回结果
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": 0,
                "totalPages": 0
            }
        }

        # ── 1. 检查家属绑定（仅 active，支持多患者） ──
        if USE_CLOUD_DB:
            cursor.execute(
                "SELECT patient_id, name, created_at, status FROM family_bindings WHERE family_id=%s AND status='active' ORDER BY created_at DESC",
                (user_id,)
            )
        else:
            cursor.execute(
                "SELECT patient_id, name, created_at, status FROM family_bindings WHERE family_id=? AND status='active' ORDER BY created_at DESC",
                (user_id,)
            )
        family_rows = cursor.fetchall()
        if family_rows:
            result["hasFamilyBinding"] = True
            family_patients = []
            max_risk = "none"
            for row in family_rows:
                r = dict(row) if not isinstance(row, dict) else row
                pid = r.get("patient_id") or r["patient_id"]
                pname = r.get("name", "") or pid
                if USE_CLOUD_DB:
                    cursor.execute(
                        "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=%s ORDER BY datetime DESC LIMIT 1",
                        (pid,)
                    )
                else:
                    cursor.execute(
                        "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=? ORDER BY datetime DESC LIMIT 1",
                        (pid,)
                    )
                meas = cursor.fetchone()
                risk = "none"; sbp = None; dbp = None; hr = None; d = None
                if meas:
                    sbp = int(meas["sbp"] or 0)
                    dbp = int(meas["dbp"] or 0)
                    hr = int(meas["hr"] or 0)
                    rl = meas["risk_level"] if "risk_level" in meas.keys() else ""
                    d = str(meas["datetime"])[:10]
                    if rl == "high" or sbp >= 160 or dbp >= 100:
                        risk = "high"
                    elif rl == "moderate" or sbp >= 140 or dbp >= 90:
                        risk = "moderate"
                    elif sbp > 0:
                        risk = "normal"
                if risk == "high" or (risk == "moderate" and max_risk != "high"):
                    max_risk = risk
                family_patients.append({
                    "patientId": pid,
                    "patientName": pname,
                    "risk": risk,
                    "sbp": sbp,
                    "dbp": dbp,
                    "hr": hr,
                    "date": d
                })

            result["familyPatients"] = family_patients
            result["familyAlertRisk"] = max_risk
            fp = family_patients[0]
            result["familyAlertSummary"] = {
                "patientId": fp["patientId"],
                "patientName": fp["patientName"],
                "risk": fp["risk"],
                "sbp": fp["sbp"],
                "dbp": fp["dbp"],
                "date": fp["date"]
            }

        # ── 2. 检查医生绑定（分页 + 性能优化） ──
        # 3. 先获取医生绑定的总患者数
        if USE_CLOUD_DB:
            cursor.execute("SELECT COUNT(*) as cnt FROM doctor_bindings WHERE doctor_id=%s AND status='active'", (user_id,))
        else:
            cursor.execute("SELECT COUNT(*) as cnt FROM doctor_bindings WHERE doctor_id=? AND status='active'", (user_id,))
        total_patients = cursor.fetchone()['cnt']

        if total_patients > 0:
            result["hasDoctorBinding"] = True
            result["pagination"]["total"] = total_patients
            result["pagination"]["totalPages"] = (total_patients + page_size - 1) // page_size

            # 4. 使用优化的SQL语句，一次性获取分页后的患者及其最新测量数据
            if USE_CLOUD_DB:
                # MySQL 使用窗口函数
                sql = """
                    SELECT 
                        b.patient_id, b.doctor_name, b.hospital, b.department,
                        m.sbp, m.dbp, m.hr, m.risk_level, m.datetime
                    FROM 
                        doctor_bindings b
                    LEFT JOIN (
                        SELECT 
                            user_id, sbp, dbp, hr, risk_level, datetime,
                            ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY datetime DESC) as rn
                        FROM measurements
                    ) m ON b.patient_id = m.user_id AND m.rn = 1
                    WHERE b.doctor_id = %s AND b.status = 'active'
                    ORDER BY b.created_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(sql, (user_id, page_size, offset))
            else:
                # SQLite 不支持窗口函数，使用相关子查询
                # 修正：先分页获取绑定的 patient_id，再进行 JOIN 查询，避免全表扫描
                sql = """
                    SELECT 
                        p.patient_id, p.doctor_name, p.hospital, p.department,
                        m.sbp, m.dbp, m.hr, m.risk_level, m.datetime
                    FROM 
                    (SELECT * FROM doctor_bindings WHERE doctor_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT ? OFFSET ?) AS p
                    LEFT JOIN 
                    measurements AS m ON p.patient_id = m.user_id AND m.datetime = (SELECT MAX(datetime) FROM measurements WHERE user_id = p.patient_id)
                """
                cursor.execute(sql, (user_id, page_size, offset))

            doctor_rows = cursor.fetchall()

            doctor_patients = []
            high_count = moderate_count = normal_count = unmonitored_count = 0
            for row in doctor_rows:
                # 5. 直接处理合并后的数据，不再需要额外查询
                r = dict(row)
                pid = r["patient_id"]
                risk = "none"; sbp = None; dbp = None; hr = None; d = None
                
                if r.get("sbp") is None:
                    unmonitored_count += 1
                    risk = "none"
                else:
                    sbp = int(r["sbp"] or 0)
                    dbp = int(r["dbp"] or 0)
                    hr = int(r["hr"] or 0)
                    rl = r.get("risk_level", "")
                    d = str(r["datetime"])[:10] if r.get("datetime") else None

                    if rl == "high" or sbp >= 160 or dbp >= 100:
                        high_count += 1; risk = "high"
                    elif rl == "moderate" or sbp >= 140 or dbp >= 90:
                        moderate_count += 1; risk = "moderate"
                    elif sbp > 0:
                        normal_count += 1; risk = "normal"
                doctor_patients.append({
                    "patientId": pid,
                    "doctorName": r.get("doctor_name", ""),
                    "hospital": r.get("hospital", ""),
                    "department": r.get("department", ""),
                    "risk": risk,
                    "sbp": sbp,
                    "dbp": dbp,
                    "hr": hr,
                    "date": d
                })

            result["doctorPatients"] = doctor_patients
            # 注意：这里的风险统计只反映当前页，如果需要全量统计，需要额外查询
            result["doctorAlertCount"] = high_count + moderate_count
            result["doctorAlertSummary"] = {
                "totalPatients": total_patients, # 使用总数
                "highRiskCount": high_count, # 仅当前页
                "moderateRiskCount": moderate_count,
                "normalCount": normal_count,
                "unmonitoredCount": unmonitored_count
            }

        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /get_patients_risk_summary  医生查看患者风险汇总
# ──────────────────────────────────────────────
@binding_bp.route("/get_patients_risk_summary", methods=["GET"])
def get_patients_risk_summary():
    doctor_id = request.args.get("doctorId", "").strip()
    if not doctor_id:
        return jsonify({"error": "缺少 doctorId 参数"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("SELECT patient_id FROM doctor_bindings WHERE doctor_id = %s AND status='active'", (doctor_id,))
        else:
            cursor.execute("SELECT patient_id FROM doctor_bindings WHERE doctor_id = ? AND status='active'", (doctor_id,))
        bindings = cursor.fetchall()
        patient_ids = [row["patient_id"] for row in bindings]

        if not patient_ids:
            return jsonify({"code": 0, "highRiskCount": 0, "moderateRiskCount": 0, "unmonitoredCount": 0, "details": {}})

        risk_detail = {}
        high_count = moderate_count = unmonitored_count = 0

        for pid in patient_ids:
            if USE_CLOUD_DB:
                cursor.execute("SELECT sbp, dbp, datetime, risk_level FROM measurements WHERE user_id = %s ORDER BY datetime DESC LIMIT 1", (pid,))
            else:
                cursor.execute("SELECT sbp, dbp, datetime, risk_level FROM measurements WHERE user_id = ? ORDER BY datetime DESC LIMIT 1", (pid,))
            row = cursor.fetchone()
            if not row:
                unmonitored_count += 1
                risk_detail[pid] = {"risk": "none", "sbp": None, "dbp": None, "date": None}
                continue

            sbp = int(row["sbp"] or 0)
            dbp = int(row["dbp"] or 0)
            rl = row["risk_level"] if "risk_level" in row.keys() else ""

            if rl == "high" or sbp >= 160 or dbp >= 100:
                high_count += 1
                risk_detail[pid] = {"risk": "high", "sbp": sbp, "dbp": dbp, "date": str(row["datetime"])[:10]}
            elif rl == "moderate" or sbp >= 140 or dbp >= 90:
                moderate_count += 1
                risk_detail[pid] = {"risk": "moderate", "sbp": sbp, "dbp": dbp, "date": str(row["datetime"])[:10]}
            else:
                risk_detail[pid] = {"risk": "normal", "sbp": sbp, "dbp": dbp, "date": str(row["datetime"])[:10]}

        return jsonify({
            "code": 0,
            "highRiskCount": high_count,
            "moderateRiskCount": moderate_count,
            "unmonitoredCount": unmonitored_count,
            "details": risk_detail
        })
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v9 /generate_invite_token  生成邀请链接 Token（用于分享路径）
# ──────────────────────────────────────────────
@binding_bp.route("/generate_invite_token", methods=["POST"])
def generate_invite_token():
    """生成永久邀请 Token，返回 token 字符串用于分享链接"""
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    patient_id = data.get("patientId") or data.get("user_id")
    role = data.get("role", "family").strip()
    if not patient_id:
        return jsonify({"error": "缺少 patientId"}), 400
    if role not in ("family", "doctor"):
        return jsonify({"error": "role 必须是 family 或 doctor"}), 400

    # 验证患者存在
    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("SELECT user_id FROM users WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT user_id FROM users WHERE user_id=?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "患者不存在"}), 404

        # 生成 32 位随机 token
        token = secrets.token_hex(16)

        # 写入 invite_tokens 表（30 天有效期）
        if USE_CLOUD_DB:
            cursor.execute("""
                INSERT INTO invite_tokens (token, patient_id, role, expires_at)
                VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL 30 DAY))
            """, (token, patient_id, role))
        else:
            cursor.execute("""
                INSERT INTO invite_tokens (token, patient_id, role, expires_at)
                VALUES (?, ?, ?, datetime('now', '+30 days'))
            """, (token, patient_id, role))
        conn.commit()

        print(f"🔗 [DB] 生成邀请 Token: {token[:8]}... → {patient_id} ({role})", flush=True)
        return jsonify({"code": 0, "data": {"token": token, "expiresIn": "30天"}})
    except Exception as e:
        return jsonify({"error": "生成失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v9 /validate_invite_token  验证邀请 Token（分享链接入口）
# ──────────────────────────────────────────────
@binding_bp.route("/validate_invite_token", methods=["POST"])
def validate_invite_token():
    """验证分享链接中的 Token，返回患者摘要"""
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "缺少 token"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("SELECT * FROM invite_tokens WHERE token=%s", (token,))
        else:
            cursor.execute("SELECT * FROM invite_tokens WHERE token=?", (token,))
        token_row = cursor.fetchone()

        if not token_row:
            return jsonify({"error": "邀请链接无效"}), 404

        token_row = dict(token_row)
        if token_row.get("used"):
            return jsonify({"error": "该邀请链接已被使用"}), 400

        expires_str = token_row.get("expires_at")
        if expires_str:
            try:
                expires_at = datetime.strptime(str(expires_str)[:19], "%Y-%m-%d %H:%M:%S")
                if datetime.now() > expires_at:
                    return jsonify({"error": "邀请链接已过期（30天有效），请联系患者重新发送"}), 400
            except Exception:
                pass

        patient_id = token_row.get("patient_id")
        role = token_row.get("role", "family")

        # 获取患者信息
        if USE_CLOUD_DB:
            cursor.execute("SELECT name, age, gender FROM users WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT name, age, gender FROM users WHERE user_id=?", (patient_id,))
        user = cursor.fetchone()

        # 获取最近测量
        if USE_CLOUD_DB:
            cursor.execute(
                "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=%s ORDER BY datetime DESC LIMIT 1",
                (patient_id,)
            )
        else:
            cursor.execute(
                "SELECT sbp, dbp, hr, risk_level, datetime FROM measurements WHERE user_id=? ORDER BY datetime DESC LIMIT 1",
                (patient_id,)
            )
        latest = cursor.fetchone()

        # 获取测量次数
        if USE_CLOUD_DB:
            cursor.execute("SELECT COUNT(*) as cnt FROM measurements WHERE user_id=%s", (patient_id,))
        else:
            cursor.execute("SELECT COUNT(*) as cnt FROM measurements WHERE user_id=?", (patient_id,))
        count_row = cursor.fetchone()

        patient_name = user["name"] if user else ""
        patient_info = {
            "patientId": patient_id,
            "patientName": patient_name,
            "role": role,
            "age": user["age"] if user else 0,
            "gender": user["gender"] if user else "",
            "totalMeasurements": count_row["cnt"] if count_row else 0,
            "latest": None
        }
        if latest:
            patient_info["latest"] = {
                "sbp": latest["sbp"],
                "dbp": latest["dbp"],
                "hr": latest["hr"],
                "risk_level": latest["risk_level"],
                "datetime": str(latest["datetime"])[:16] if latest["datetime"] else ""
            }

        return jsonify({"code": 0, "data": patient_info})
    except Exception as e:
        return jsonify({"error": "验证失败", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# ★ v9 /bind_by_token  通过 Token 直接绑定（分享链接确认入口）
# ──────────────────────────────────────────────
@binding_bp.route("/bind_by_token", methods=["POST"])
def bind_by_token():
    """通过分享 Token 确认绑定（一步 active）"""
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    token = (data.get("token") or "").strip()
    viewer_id = data.get("viewerId") or ""
    viewer_name = data.get("viewerName") or data.get("name") or ""
    hospital = data.get("hospital", "").strip()
    department = data.get("department", "").strip()

    if not token:
        return jsonify({"error": "缺少 token"}), 400
    if not viewer_id:
        return jsonify({"error": "缺少 viewerId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        # 验证 token
        if USE_CLOUD_DB:
            cursor.execute("SELECT * FROM invite_tokens WHERE token=%s", (token,))
        else:
            cursor.execute("SELECT * FROM invite_tokens WHERE token=?", (token,))
        token_row = cursor.fetchone()
        if not token_row:
            return jsonify({"error": "邀请链接无效"}), 404
        token_row = dict(token_row)
        if token_row.get("used"):
            return jsonify({"error": "该邀请已被使用"}), 400
        expires_str = token_row.get("expires_at")
        if expires_str:
            try:
                expires_at = datetime.strptime(str(expires_str)[:19], "%Y-%m-%d %H:%M:%S")
                if datetime.now() > expires_at:
                    return jsonify({"error": "邀请链接已过期"}), 400
            except Exception:
                pass

        patient_id = token_row.get("patient_id")
        role = token_row.get("role", "family")

        if viewer_id == patient_id:
            return jsonify({"error": "不能绑定自己"}), 400

        # 根据 role 选择表
        if role == "doctor":
            table = "doctor_bindings"
            viewer_col = "doctor_id"
            viewer_name_col = "doctor_name"
            default_name = "医生"
        else:
            table = "family_bindings"
            viewer_col = "family_id"
            viewer_name_col = "name"
            default_name = "家人"

        # 检查是否已存在 active 绑定（幂等）
        if USE_CLOUD_DB:
            cursor.execute(f"SELECT status FROM {table} WHERE {viewer_col}=%s AND patient_id=%s", (viewer_id, patient_id))
        else:
            cursor.execute(f"SELECT status FROM {table} WHERE {viewer_col}=? AND patient_id=?", (viewer_id, patient_id))
        existing = cursor.fetchone()

        if existing and existing["status"] == "active":
            conn.commit()
            return jsonify({"code": 0, "status": "active", "message": "已绑定（无需重复操作）", "patientId": patient_id, "role": role})

        # 一步写入 active
        if existing:
            if role == "doctor":
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=%s, hospital=%s, department=%s, status='active' WHERE {viewer_col}=%s AND patient_id=%s",
                        (viewer_name or default_name, hospital, department, viewer_id, patient_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=?, hospital=?, department=?, status='active' WHERE {viewer_col}=? AND patient_id=?",
                        (viewer_name or default_name, hospital, department, viewer_id, patient_id)
                    )
            else:
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=%s, status='active' WHERE {viewer_col}=%s AND patient_id=%s",
                        (viewer_name or default_name, viewer_id, patient_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE {table} SET {viewer_name_col}=?, status='active' WHERE {viewer_col}=? AND patient_id=?",
                        (viewer_name or default_name, viewer_id, patient_id)
                    )
        else:
            if role == "doctor":
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"INSERT INTO {table} (doctor_id, patient_id, doctor_name, hospital, department, status) VALUES (%s, %s, %s, %s, %s, 'active')",
                        (viewer_id, patient_id, viewer_name or default_name, hospital, department)
                    )
                else:
                    cursor.execute(
                        f"INSERT INTO {table} (doctor_id, patient_id, doctor_name, hospital, department, status) VALUES (?, ?, ?, ?, ?, 'active')",
                        (viewer_id, patient_id, viewer_name or default_name, hospital, department)
                    )
            else:
                if USE_CLOUD_DB:
                    cursor.execute(
                        f"INSERT INTO {table} (family_id, patient_id, name, status) VALUES (%s, %s, %s, 'active')",
                        (viewer_id, patient_id, viewer_name or default_name)
                    )
                else:
                    cursor.execute(
                        f"INSERT INTO {table} (family_id, patient_id, name, status) VALUES (?, ?, ?, 'active')",
                        (viewer_id, patient_id, viewer_name or default_name)
                    )

        # 标记 token 已用
        if USE_CLOUD_DB:
            cursor.execute("UPDATE invite_tokens SET used=1, used_by=%s WHERE token=%s", (viewer_id, token))
        else:
            cursor.execute("UPDATE invite_tokens SET used=1, used_by=? WHERE token=?", (viewer_id, token))

        conn.commit()
        print(f"✅ [DB] Token 绑定成功: {viewer_id} → {patient_id} ({role})", flush=True)
        return jsonify({"code": 0, "status": "active", "message": "绑定成功", "patientId": patient_id, "role": role})
    except Exception as e:
        return jsonify({"error": "绑定失败", "detail": str(e)}), 500

