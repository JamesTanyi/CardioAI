#!/usr/bin/env python
"""
BloodTrack CloudRun 主入口
"""

import os
import sys
from flask import Flask, request, jsonify
from datetime import datetime

# -----------------------------
# 解决 CloudRun 下的路径问题
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

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
# 时间字段规范化函数（必须放在 analyze() 前）
# -----------------------------
def _normalize_record_time(rec):
    """
    兼容 timestamp / datetime 字段：
    - 自动解析字符串为 datetime 对象
    - 最终 rec["datetime"] 一定存在
    """
    if rec is None:
        return rec

    # 复制一份，避免修改原数据
    rec = dict(rec)

    ts = rec.get("datetime") or rec.get("timestamp") or rec.get("date")

    # 如果是字符串，尝试解析
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                rec["datetime"] = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue

    # 如果解析失败或没有 timestamp，至少给一个当前时间
    if "datetime" not in rec:
        rec["datetime"] = datetime.now()

    # 计算脉压 PP (增强健壮性：确保只要有血压值就计算 pp)
    if "sbp" in rec and "dbp" in rec:
        rec["pp"] = rec.get("pp", rec["sbp"] - rec["dbp"])
    elif "pp" not in rec:
        rec["pp"] = 40

    # 默认心率
    if "hr" not in rec:
        rec["hr"] = 70

    return rec

# -----------------------------
# Flask 应用
# -----------------------------
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return "Python service is running"

@app.route("/analyze", methods=["POST"])  # ✅ 修复：与小程序路由对齐
def analyze():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400
    print(f"📥 [Request] 收到 /analyze 请求", flush=True)
    
    if not data:
        return jsonify({"error": "Empty request body"}), 400
        
    # 检查引擎是否加载成功
    if EngineClass is None:
        return jsonify({"code": -1, "error": "Engine load failed", "detail": EngineError}), 500

    history = data.get("history", [])
    current = data.get("current")

    if current is None:
        return jsonify({"error": "Missing 'current' record"}), 400

    if not isinstance(history, list):
        return jsonify({"error": "'history' must be a list"}), 400

    # ⭐ 规范化时间字段
    history = [_normalize_record_time(r) for r in history]
    current = _normalize_record_time(current)
    
    print(f"📊 [Data] 历史记录数: {len(history)}, 当前测量时间: {current['datetime']}", flush=True)

    try:
        print("🚀 [Engine] 开始初始化引擎...", flush=True)
        engine = EngineClass(history, current)
        result = engine.run_all_diagnostics()
        print(f"✅ [Engine] 分析完成. 风险等级: {result.get('risk_level')}", flush=True)
        return jsonify({
            "code": 0,
            "data": result
        })

    except Exception as e:
        return jsonify({
            "error": "Engine execution failed",
            "detail": str(e)
        }), 500

# -----------------------------
# 本地运行
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
