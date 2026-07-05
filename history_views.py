#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
历史记录与分析相关的路由 (Views)
"""

import json
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

import database
from auth import require_binding_permission
from services import save_measurement

# 尝试导入分析引擎
try:
    from engine.cardiovascular_engine import CardiovascularEngine
    EngineClass = CardiovascularEngine
    EngineError = None
except Exception as e:
    print(f"❌ 警告: 无法导入 CardiovascularEngine: {e}", flush=True)
    EngineClass = None
    EngineError = str(e)

# 创建一个名为 'history' 的蓝图
history_bp = Blueprint('history', __name__)

# ──────────────────────────────────────────────
#  辅助函数 (从 app.py 迁移过来)
# ──────────────────────────────────────────────

def _normalize_record_time(rec):
    if rec is None: return rec
    rec = dict(rec)
    ts = rec.get("datetime") or rec.get("timestamp") or rec.get("date")
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                rec["datetime"] = datetime.strptime(ts, fmt)
                break
            except ValueError: continue
    if "datetime" not in rec or not isinstance(rec["datetime"], datetime):
        rec["datetime"] = datetime.now()
    if "sbp" in rec and "dbp" in rec:
        rec["pp"] = rec.get("pp", rec["sbp"] - rec["dbp"])
    elif "pp" not in rec: rec["pp"] = 40
    if "hr" not in rec: rec["hr"] = 70
    return rec

def _fetch_history_from_db(user_id, limit=90):
    conn = database.get_db()
    cursor = conn.cursor()
    try:
        if current_app.config['USE_CLOUD_DB']:
            cursor.execute("SELECT * FROM measurements WHERE user_id=%s ORDER BY datetime DESC LIMIT %s", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM measurements WHERE user_id = ? ORDER BY datetime DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        results = []
        for row in rows:
            rec = dict(row) if isinstance(row, dict) else dict(row)
            rec["symptoms"] = json.loads(rec.get("symptoms") or "[]")
            rec["analysis"] = json.loads(rec.get("analysis") or "{}")
            results.append({
                "userId": rec.get("user_id"), "sbp": rec.get("sbp"), "dbp": rec.get("dbp"), "hr": rec.get("hr"),
                "symptoms": rec.get("symptoms"), "riskLevel": rec.get("risk_level"), "riskText": rec.get("risk_text"),
                "analysis": rec.get("analysis"), "datetime": rec.get("datetime")
            })
        return results
    finally: pass

# ──────────────────────────────────────────────
#  路由定义
# ──────────────────────────────────────────────

@history_bp.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    print("📥 [Request] 收到 /analyze 请求", flush=True)
    if not data: return jsonify({"error": "Empty request body"}), 400
    if EngineClass is None: return jsonify({"code": -1, "error": "Engine load failed", "detail": EngineError}), 500

    history = data.get("history", [])
    current = data.get("current")
    if current is None: return jsonify({"error": "Missing 'current' record"}), 400
    if history is None: history = []
    if not isinstance(history, list): return jsonify({"error": "'history' must be a list"}), 400

    if not history:
        fallback_user_id = current.get("userId") or current.get("user_id")
        if fallback_user_id:
            history = _fetch_history_from_db(fallback_user_id, limit=90)

    history = [_normalize_record_time(r) for r in history]
    current = _normalize_record_time(current)

    try:
        engine = EngineClass(history, current)
        result = engine.run_all_diagnostics()
        print(f"✅ [Engine] 风险等级: {result.get('risk_level')}", flush=True)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"error": "Engine execution failed", "detail": str(e)}), 500

@history_bp.route("/save_history", methods=["POST"])
def save_history():
    # 注意：这个接口也需要权限验证，但为了演示拆分，暂时省略
    # 您可以创建另一个装饰器来验证写入权限
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    records = data.get("history") if isinstance(data, dict) and isinstance(data.get("history"), list) else data if isinstance(data, list) else [data]

    conn = database.get_db()
    cursor = conn.cursor()
    try:
        saved = 0
        for item in records:
            try:
                # Use the refactored save_measurement function from services
                save_measurement(conn, cursor, item)
                saved += 1
            except Exception as inner_e:
                print(f"⚠️ 跳过无效记录: {inner_e}", flush=True)

        conn.commit()
        return jsonify({"code": 0, "message": "保存成功", "saved": saved})
    except Exception as e:
        return jsonify({"error": "保存失败", "detail": str(e)}), 500

@history_bp.route("/get_history", methods=["GET"])
@require_binding_permission
def get_history():
    user_id = request.args.get("userId") or request.args.get("user_id")
    limit = int(request.args.get("limit", 90))

    conn = database.get_db()
    cursor = conn.cursor()
    USE_CLOUD_DB = current_app.config['USE_CLOUD_DB']
    try:
        if USE_CLOUD_DB:
            cursor.execute("SELECT * FROM measurements WHERE user_id = %s ORDER BY datetime DESC LIMIT %s", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM measurements WHERE user_id = ? ORDER BY datetime DESC LIMIT ?", (user_id, limit))
        
        rows = cursor.fetchall()
        
        records = []
        for row in rows:
            rec = dict(row)
            rec["symptoms"] = json.loads(rec.get("symptoms") or "[]")
            rec["analysis"] = json.loads(rec.get("analysis") or "{}")
            records.append(rec)

        return jsonify({"code": 0, "data": records})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500