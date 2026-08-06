# -*- coding: utf-8 -*-
# app.py
import os
from flask import Flask, jsonify
import database

from history_views import history_bp
from binding_views import binding_bp
from measure_views import measure_bp # 核心分析蓝图
from feedback_views import feedback_bp # 三方留言反馈蓝图

app = Flask(__name__)
database.init_app(app)

@app.route("/", methods=["GET"])
def health():
    return "Cardiovascular Health Baseline Analysis System Engine is running."

# 统一注入路由管道契约前缀 /api
app.register_blueprint(history_bp, url_prefix='/api')
app.register_blueprint(binding_bp, url_prefix='/api')
app.register_blueprint(measure_bp, url_prefix='/api')
app.register_blueprint(feedback_bp, url_prefix='/api')

@app.errorhandler(404)
def page_not_found(e):
    # ★ 改：之前这里把所有不存在的路由都返回 HTTP 200 + "success"，
    #   会把真正的404错误(路由拼写错误/漏注册蓝图)伪装成"成功"，小程序端
    #   wx.request 的 success 回调会正常触发而不是走 fail/catch，排查起来很困难。
    #   改成诚实的404，路由真的不存在就应该让调用方知道。
    return jsonify({"code": 404, "msg": "接口不存在", "data": None}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)