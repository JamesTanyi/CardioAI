#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
历史记录相关的路由 (Views)

★ 说明：原文件中的 `/analyze` 路由（history_bp.analyze）已删除。
   该路由与 measure_views.py 里的 measure_bp.analyze_measurement()
   同时挂在 /api 前缀下、同为 POST /api/analyze，注册顺序上
   history_bp 先于 measure_bp 注册，导致 Flask/Werkzeug 实际上
   一直把请求路由到这里的旧版本 analyze()，而不是新版本的
   measure_bp.analyze_measurement()（真正负责存库+调用引擎的那个）。
   经实测确认（POST /api/analyze 返回 "Missing 'current' record"，
   即本文件旧版 analyze() 的错误文案）问题属实，故将其连同专属的
   辅助函数（_normalize_record_time、_fetch_history_from_db）
   和专属的 engine 导入一并移除，避免死代码和路由冲突。
   本文件现在只保留 save_history 和 get_history 两个真正在用的接口。
"""

import json
from flask import Blueprint, request, jsonify, current_app

import database
from auth import require_binding_permission
from services import save_measurement

# 创建一个名为 'history' 的蓝图
history_bp = Blueprint('history', __name__)

# ──────────────────────────────────────────────
#  路由定义
# ──────────────────────────────────────────────

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