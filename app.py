#!/usr/bin/env python
"""
BloodTrack CloudRun 主入口
"""

import os
import sys
import sqlite3
import json
from flask import Flask, request, jsonify
from datetime import datetime

# -----------------------------
# 解决 CloudRun 下的路径问题
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# -----------------------------
# SQLite 数据库路径
# 使用 /tmp 目录，CloudRun 容器可写
# 注意：容器重启后数据丢失（测试阶段够用，上线换 MySQL 只改此处）
# -----------------------------
DB_PATH = os.environ.get("DB_PATH", "/tmp/bloodtrack.db")

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 返回字典格式
    return conn

def init_db():
    """初始化数据库表"""
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
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    print("✅ [DB] SQLite 初始化完成", flush=True)

# -----------------------------
# 导入你的 engine 逻辑
# -----------------------------
try:
    from engine.cardiovascular_engine import CardiovascularEngine
    EngineClass = CardiovascularEngine
    EngineError = None
except Exception as e:
    print(f"❌ 警告: 无法导入 CardiovascularEngine: {e}", flush=True)
    EngineClass = None
    EngineError = str(e)

# -----------------------------
# 时间字段规范化函数
# -----------------------------
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

# -----------------------------
# Flask 应用
# -----------------------------
app = Flask(__name__)

# 启动时初始化数据库
init_db()

@app.route("/", methods=["GET"])
def health():
    return "Python service is running"


# -----------------------------
# /analyze - 核心分析接口（原有逻辑不变）
# -----------------------------
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    print(f"📥 [Request] 收到 /analyze 请求", flush=True)

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

    print(f"📊 [Data] 历史记录数: {len(history)}, 当前测量时间: {current['datetime']}", flush=True)

    try:
        print("🚀 [Engine] 开始初始化引擎...", flush=True)
        engine = EngineClass(history, current)
        result = engine.run_all_diagnostics()
        print(f"✅ [Engine] 分析完成. 风险等级: {result.get('risk_level')}", flush=True)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"error": "Engine execution failed", "detail": str(e)}), 500


# -----------------------------
# /save_history - 保存测量记录
# -----------------------------
@app.route("/save_history", methods=["POST"])
def save_history():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400

    user_id  = data.get("userId") or data.get("user_id")
    sbp      = data.get("sbp")
    dbp      = data.get("dbp")
    datetime_str = data.get("date") or data.get("datetime")

    if not all([user_id, sbp, dbp, datetime_str]):
        return jsonify({"error": "缺少必要字段: userId / sbp / dbp / date"}), 400

    conn = get_db()
    try:
        # 自动注册用户（首次）
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )
        # 保存测量记录
        conn.execute("""
            INSERT INTO measurements
                (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            int(sbp),
            int(dbp),
            int(data.get("hr", 75)),
            json.dumps(data.get("symptoms", []), ensure_ascii=False),
            data.get("riskLevel", "normal"),
            data.get("riskText", ""),
            json.dumps(data.get("analysis", {}), ensure_ascii=False),
            datetime_str
        ))
        conn.commit()
        print(f"💾 [DB] 已保存记录: {user_id} {datetime_str} {sbp}/{dbp}", flush=True)
        return jsonify({"code": 0, "message": "保存成功"})
    except Exception as e:
        return jsonify({"error": "保存失败", "detail": str(e)}), 500
    finally:
        conn.close()


# -----------------------------
# /get_history - 获取历史记录
# -----------------------------
@app.route("/get_history", methods=["GET"])
def get_history():
    user_id = request.args.get("userId") or request.args.get("user_id")
    limit   = int(request.args.get("limit", 90))  # 默认最近90条

    if not user_id:
        return jsonify({"error": "缺少 userId 参数"}), 400

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM measurements
            WHERE user_id = ?
            ORDER BY datetime DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()

        records = []
        for row in rows:
            rec = dict(row)
            # 反序列化 JSON 字段
            rec["symptoms"] = json.loads(rec.get("symptoms") or "[]")
            rec["analysis"] = json.loads(rec.get("analysis") or "{}")
            records.append(rec)

        print(f"📤 [DB] 查询历史: {user_id}, 返回 {len(records)} 条", flush=True)
        return jsonify({"code": 0, "data": records})
    except Exception as e:
        return jsonify({"error": "查询失败", "detail": str(e)}), 500
    finally:
        conn.close()


# -----------------------------
# 本地运行
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
