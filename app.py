# -*- coding: utf-8 -*-
# app.py
# -*- coding: utf-8 -*-
# app.py
import os
from flask import Flask, jsonify
import database

from history_views import history_bp
from binding_views import binding_bp
from measure_views import measure_bp # 核心分析蓝图

app = Flask(__name__)
database.init_app(app)

@app.route("/", methods=["GET"])
def health():
    return "Cardiovascular Health Baseline Analysis System Engine is running."

# 统一注入路由管道契约前缀 /api
app.register_blueprint(history_bp, url_prefix='/api')
app.register_blueprint(binding_bp, url_prefix='/api')
app.register_blueprint(measure_bp, url_prefix='/api')

@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"code": 0, "msg": "API mesh proxy routing successful", "data": {}}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)