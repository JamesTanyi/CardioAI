#!/usr/bin/env python
"""
BloodTrack CloudRun 主入口
"""

import os
import sys
import json
from flask import Flask, request, jsonify
from datetime import datetime

# 数据库配置
USE_CLOUD_DB = os.environ.get("USE_CLOUD_DB", "true").lower() == "true"

if USE_CLOUD_DB:
    # 使用腾讯云 MySQL
    import pymysql
    DB_CONFIG = {
        'host': os.environ.get("DB_HOST", "10.0.0.100"),  # 云托管内网地址
        'port': int(os.environ.get("DB_PORT", 3306)),
        'user': os.environ.get("DB_USER", "root"),
        'password': os.environ.get("DB_PASSWORD", ""),
        'database': os.environ.get("DB_NAME", "cardioai"),
        'charset': 'utf8mb4'
    }
    print("✅ 使用腾讯云 MySQL 数据库", flush=True)
    
    def get_db():
        conn = pymysql.connect(**DB_CONFIG)
        conn.cursorclass = pymysql.cursors.DictCursor
        return conn
    
    def init_db():
        conn = get_db()
        cursor = conn.cursor()
        
        # measurements 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                user_id     VARCHAR(100) NOT NULL,
                sbp         INT NOT NULL,
                dbp         INT NOT NULL,
                hr          INT DEFAULT 75,
                symptoms    TEXT DEFAULT '[]',
                risk_level  VARCHAR(20) DEFAULT 'normal',
                risk_text   TEXT DEFAULT '',
                analysis    TEXT DEFAULT '{}',
                datetime    VARCHAR(50) NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_id (user_id),
                INDEX idx_datetime (datetime)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        # users 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                user_id     VARCHAR(100) UNIQUE NOT NULL,
                name        VARCHAR(50) DEFAULT '',
                age         INT DEFAULT 0,
                gender      VARCHAR(10) DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        # family_bindings 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS family_bindings (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                family_id   VARCHAR(100) NOT NULL,
                patient_id  VARCHAR(100) NOT NULL,
                name        VARCHAR(50) NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_binding (family_id, patient_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        # feedbacks 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                from_id     VARCHAR(100) NOT NULL,
                from_role   VARCHAR(20) NOT NULL,
                to_id       VARCHAR(100) NOT NULL,
                content     TEXT NOT NULL,
                is_read     INT DEFAULT 0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_to_id (to_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        conn.commit()
        conn.close()
        print("✅ [DB] MySQL 初始化完成", flush=True)
else:
    # 使用本地 SQLite（仅开发测试用）
    import sqlite3
    DB_PATH = os.environ.get("DB_PATH", "/tmp/bloodtrack.db")
    print("⚠️ 使用本地 SQLite 数据库（仅开发测试）", flush=True)
    
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db():
        conn = get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                sbp         INTEGER NOT NULL,
                dbp         INTEGER NOT NULL,
                hr          INTEGER DEFAULT 75,
                symptoms    TEXT DEFAULT '[]',
                risk_level  TEXT DEFAULT 'normal',
                risk_text   TEXT DEFAULT '',
                analysis    TEXT DEFAULT '{}',
                datetime    TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT UNIQUE NOT NULL,
                name        TEXT DEFAULT '',
                age         INTEGER DEFAULT 0,
                gender      TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS family_bindings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id   TEXT NOT NULL,
                patient_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(family_id, patient_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id     TEXT NOT NULL,
                from_role   TEXT NOT NULL,
                to_id       TEXT NOT NULL,
                content     TEXT NOT NULL,
                is_read     INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
        print("✅ [DB] SQLite 初始化完成", flush=True)

try:
    from engine.cardiovascular_engine import CardiovascularEngine
    EngineClass = CardiovascularEngine
    EngineError = None
except Exception as e:
    print(f"❌ 警告: 无法导入 CardiovascularEngine: {e}", flush=True)
    EngineClass = None
    EngineError = str(e)

def _normalize_record_time(rec):
    if rec is None:
        return rec
    rec = dict(rec)
    ts = rec.get("datetime") or rec.get("timestamp") or rec.get("date")
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                rec["datetime"] = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue
    if "datetime" not in rec or not isinstance(rec["datetime"], datetime):
        rec["datetime"] = datetime.now()
    if "sbp" in rec and "dbp" in rec:
        rec["pp"] = rec.get("pp", rec["sbp"] - rec["dbp"])
    elif "pp" not in rec:
        rec["pp"] = 40
    if "hr" not in rec:
        rec["hr"] = 70
    return rec

app = Flask(__name__)
init_db()

@app.route("/", methods=["GET"])
def health():
    return "Python service is running"

# ──────────────────────────────────────────────
# /analyze  核心分析
# ──────────────────────────────────────────────
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    print("📥 [Request] 收到 /analyze 请求", flush=True)
    if not data:
        return jsonify({"error": "Empty request body"}), 400
    if EngineClass is None:
        return jsonify({"code": -1, "error": "Engine load failed", "detail": EngineError}), 500

    history = data.get("history", [])
    current = data.get("current")
    if current is None:
        return jsonify({"error": "Missing 'current' record"}), 400
    if not isinstance(history, list):
        return jsonify({"error": "'history' must be a list"}), 400

    history = [_normalize_record_time(r) for r in history]
    current = _normalize_record_time(current)

    try:
        engine = EngineClass(history, current)
        result = engine.run_all_diagnostics()
        print(f"✅ [Engine] 风险等级: {result.get('risk_level')}", flush=True)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"error": "Engine execution failed", "detail": str(e)}), 500

# ──────────────────────────────────────────────
# /save_history  保存测量记录
# ──────────────────────────────────────────────
@app.route("/save_history", methods=["POST"])
def save_history():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    user_id      = data.get("userId") or data.get("user_id")
    sbp          = data.get("sbp")
    dbp          = data.get("dbp")
    datetime_str = data.get("date") or data.get("datetime")

    if not all([user_id, sbp, dbp, datetime_str]):
        return jsonify({"error": "缺少必要字段: userId / sbp / dbp / date"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        if USE_CLOUD_DB:
            # MySQL 语法
            cursor.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,))
            cursor.execute("""
                INSERT INTO measurements
                    (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                user_id,
                int(sbp), int(dbp),
                int(data.get("hr", 75)),
                json.dumps(data.get("symptoms", []), ensure_ascii=False),
                data.get("riskLevel", "normal"),
                data.get("riskText", ""),
                json.dumps(data.get("analysis", {}), ensure_ascii=False),
                datetime_str
            ))
        else:
            # SQLite 语法
            cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            cursor.execute("""
                INSERT INTO measurements
                    (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                int(sbp), int(dbp),
                int(data.get("hr", 75)),
                json.dumps(data.get("symptoms", []), ensure_ascii=False),
                data.get("riskLevel", "normal"),
                data.get("riskText", ""),
                json.dumps(data.get("analysis", {}), ensure_ascii=False),
                datetime_str
            ))
        conn.commit()
        print(f"💾 [DB] 保存: {user_id} {datetime_str} {sbp}/{dbp}", flush=True)
        return jsonify({"code": 0, "message": "保存成功"})
    except Exception as e:
        return jsonify({"error": "保存失败", "detail": str(e)}), 500
    finally:
        conn.close()

# ──────────────────────────────────────────────
# /get_history  读取历史（患者自己或已绑定家属/医生）
# ──────────────────────────────────────────────
@app.route("/get_history", methods=["GET"])
def get_history():
    user_id   = request.args.get("userId") or request.args.get("user_id")
    viewer_id = request.args.get("viewerId")
    limit     = int(request.args.get("limit", 90))

    if not user_id:
        return jsonify({"error": "缺少 userId 参数"}), 400

    if viewer_id and viewer_id != user_id:
        conn = get_db()
        cursor = conn.cursor()
        if USE_CLOUD_DB:
            cursor.execute(
                "SELECT id FROM family_bindings WHERE family_id=%s AND patient_id=%s",
                (viewer_id, user_id)
            )
        else:
            cursor.execute(
                "SELECT id FROM family_bindings WHERE family_id=? AND patient_id=?",
                (viewer_id, user_id)
            )
        binding = cursor.fetchone()
        conn.close()
        if not binding:
            return jsonify({"error": "无权限查看该用户数据，请先绑定"}), 403

    conn = get_db()
    cursor = conn.cursor()
    try:
        if USE_CLOUD_DB:
            cursor.execute("""
                SELECT * FROM measurements
                WHERE user_id = %s
                ORDER BY datetime DESC
                LIMIT %s
            """, (user_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM measurements
                WHERE user_id = ?
                ORDER BY datetime DESC
                LIMIT ?
            """, (user_id, limit))
        
        rows = cursor.fetchall()
        
        records = []
        for row in rows:
            rec = dict(row) if isinstance(row, dict) else dict(row)
            # MySQL 返回的是字符串，需要解析
            rec["symptoms"] = json.loads(rec.get("symptoms") or "[]")
            rec["analysis"] = json.loads(rec.get("analysis") or "{}")
            records.append(rec)

        return jsonify({"code": 0, "data": records})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500
    finally:
        conn.close()

# ──────────────────────────────────────────────
# /bind_family  家属绑定患者
# ──────────────────────────────────────────────
@app.route("/bind_family", methods=["POST"])
def bind_family():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    family_id  = data.get("familyId")
    patient_id = data.get("patientId")
    name       = data.get("name", "家人")

    if not all([family_id, patient_id]):
        return jsonify({"error": "缺少 familyId 或 patientId"}), 400
    if family_id == patient_id:
        return jsonify({"error": "不能绑定自己"}), 400

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id FROM users WHERE user_id=?", (patient_id,)
        ).fetchone()
        if not user:
            return jsonify({"error": "患者ID不存在，请确认ID是否正确"}), 404

        conn.execute("""
            INSERT OR REPLACE INTO family_bindings (family_id, patient_id, name)
            VALUES (?, ?, ?)
        """, (family_id, patient_id, name))
        conn.commit()
        print(f"🔗 [DB] 绑定: {family_id} → {patient_id} ({name})", flush=True)
        return jsonify({"code": 0, "message": "绑定成功"})
    except Exception as e:
        return jsonify({"error": "绑定失败", "detail": str(e)}), 500
    finally:
        conn.close()

# ──────────────────────────────────────────────
# /get_family_list  获取已绑定家人列表
# ──────────────────────────────────────────────
@app.route("/get_family_list", methods=["GET"])
def get_family_list():
    family_id = request.args.get("familyId")
    if not family_id:
        return jsonify({"error": "缺少 familyId 参数"}), 400

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT patient_id, name, created_at
            FROM family_bindings
            WHERE family_id = ?
            ORDER BY created_at DESC
        """, (family_id,)).fetchall()
        return jsonify({"code": 0, "data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500
    finally:
        conn.close()

# ──────────────────────────────────────────────
# /send_feedback  家属或医生发反馈给患者
# ──────────────────────────────────────────────
@app.route("/send_feedback", methods=["POST"])
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

    conn = get_db()
    try:
        binding = conn.execute(
            "SELECT id FROM family_bindings WHERE family_id=? AND patient_id=?",
            (from_id, to_id)
        ).fetchone()
        if not binding:
            return jsonify({"error": "未绑定该患者，无法发送反馈"}), 403

        conn.execute("""
            INSERT INTO feedbacks (from_id, from_role, to_id, content)
            VALUES (?, ?, ?, ?)
        """, (from_id, from_role, to_id, content))
        conn.commit()
        print(f"💬 [DB] 反馈: {from_id}({from_role}) → {to_id}", flush=True)
        return jsonify({"code": 0, "message": "反馈已发送"})
    except Exception as e:
        return jsonify({"error": "发送失败", "detail": str(e)}), 500
    finally:
        conn.close()

# ──────────────────────────────────────────────
# /get_feedback  患者查看收到的反馈
# ──────────────────────────────────────────────
@app.route("/get_feedback", methods=["GET"])
def get_feedback():
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "缺少 userId 参数"}), 400

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, from_id, from_role, content, is_read, created_at
            FROM feedbacks
            WHERE to_id = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (user_id,)).fetchall()

        feedbacks = [dict(r) for r in rows]
        unread_count = sum(1 for f in feedbacks if f["is_read"] == 0)

        conn.execute(
            "UPDATE feedbacks SET is_read=1 WHERE to_id=? AND is_read=0",
            (user_id,)
        )
        conn.commit()
        return jsonify({"code": 0, "data": feedbacks, "unread": unread_count})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500
    finally:
        conn.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
