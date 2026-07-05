#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
认证与授权模块

提供用于保护 Flask 路由的装饰器。
"""

from functools import wraps
from flask import request, jsonify, current_app
import database

def require_binding_permission(f):
    """
    一个装饰器，用于验证 viewer_id 是否有权限查看 user_id 的数据。
    权限基于 family_bindings 或 doctor_bindings 表中的 'active' 状态。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = request.args.get("userId") or request.args.get("user_id")
        viewer_id = request.args.get("viewerId")

        if not user_id:
            return jsonify({"error": "缺少 userId 参数"}), 400

        # 如果是本人查看，或未指定查看者，则直接放行
        if not viewer_id or viewer_id == user_id:
            return f(*args, **kwargs)

        # 验证绑定关系
        conn = database.get_db()
        cursor = conn.cursor()
        family_binding = None
        doctor_binding = None

        if current_app.config['USE_CLOUD_DB']:
            cursor.execute(
                "SELECT id FROM family_bindings WHERE family_id=%s AND patient_id=%s AND status='active'",
                (viewer_id, user_id)
            )
            family_binding = cursor.fetchone()
            if not family_binding:
                cursor.execute(
                    "SELECT id FROM doctor_bindings WHERE doctor_id=%s AND patient_id=%s AND status='active'",
                    (viewer_id, user_id)
                )
                doctor_binding = cursor.fetchone()
        else: # SQLite
            cursor.execute(
                "SELECT id FROM family_bindings WHERE family_id=? AND patient_id=? AND status='active'",
                (viewer_id, user_id)
            )
            family_binding = cursor.fetchone()
            if not family_binding:
                cursor.execute(
                    "SELECT id FROM doctor_bindings WHERE doctor_id=? AND patient_id=? AND status='active'",
                    (viewer_id, user_id)
                )
                doctor_binding = cursor.fetchone()

        if not family_binding and not doctor_binding:
            return jsonify({"error": "无权限查看该用户数据，请先确认绑定"}), 403

        # 权限验证通过，执行原始函数
        return f(*args, **kwargs)

    return decorated_function