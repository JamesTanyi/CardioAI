#!/usr/bin/env python
"""
BloodTrack CloudRun 主入口
"""

import os
import json
from flask import Flask, request, jsonify, current_app

import database
import auth
from history_views import history_bp
from binding_views import binding_bp

app = Flask(__name__)
database.init_app(app)

@app.route("/", methods=["GET"])
def health():
    return "Python service is running"

app.register_blueprint(history_bp, url_prefix='/api') # ★ 统一注册到 /api 前缀
app.register_blueprint(binding_bp, url_prefix='/api')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)

print("\n========= Routes =========")

for rule in app.url_map.iter_rules():
    print(rule)

print("==========================")