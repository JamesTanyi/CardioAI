#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库管理模块

负责数据库的连接、初始化和会话管理。
使用 Flask 应用上下文来自动管理连接的开启和关闭。
"""

import os
import sqlite3
import pymysql
from flask import g, current_app

def get_db():
    """
    获取当前请求的数据库连接。
    如果 g 对象中不存在连接，则创建一个新的连接并存储起来。
    """
    if 'db' not in g:
        if current_app.config['USE_CLOUD_DB']:
            g.db = _get_cloud_db()
        else:
            print("🔍 [DB] 使用本地 SQLite", flush=True)
            g.db = _get_sqlite_db()
    return g.db

def close_db(e=None):
    """
    关闭当前请求的数据库连接。
    这个函数会被注册到应用上下文中，在请求结束时自动调用。
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """根据配置初始化数据库表结构。"""
    if current_app.config['USE_CLOUD_DB']:
        _init_cloud_db()
    else:
        _init_sqlite_db()

def init_app(app):
    """
    在 Flask 应用实例上注册数据库管理功能。
    - 设置数据库配置
    - 注册 teardown 函数
    - 在应用上下文中初始化数据库
    """
    # 1. 数据库配置
    _force_sqlite = os.environ.get("FORCE_SQLITE", "").lower() == "true"
    _use_cloud_db_env = os.environ.get("USE_CLOUD_DB", "true").lower() == "true"
    USE_CLOUD_DB = _use_cloud_db_env and not _force_sqlite

    app.config['USE_CLOUD_DB'] = USE_CLOUD_DB

    if USE_CLOUD_DB:
        try:
            print("🔄 尝试连接腾讯云 MySQL 数据库...", flush=True)
            # 尝试连接一次以验证配置
            conn = _get_cloud_db()
            conn.close()
            app.config['USE_CLOUD_DB'] = True
        except Exception as mysql_err:
            print(f"❌ MySQL 连接失败: {mysql_err}", flush=True)
            print("🔽 自动降级到 SQLite 模式", flush=True)
            app.config['USE_CLOUD_DB'] = False

    if not app.config['USE_CLOUD_DB']:
        # 统一数据库路径，确保与 `完善数据库.py` 使用相同的文件
        DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bloodtrack.db")
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        
        app.config['SQLITE_DB_PATH'] = DB_PATH
        print(f"⚠️ 使用本地 SQLite 数据库: {DB_PATH}", flush=True)

    # 2. 注册 teardown 函数
    app.teardown_appcontext(close_db)

    # 3. 初始化数据库
    with app.app_context():
        init_db()


def _get_cloud_db():
    DB_CONFIG = {
        'host': os.environ.get("DB_HOST", "10.0.0.100"),
        'port': int(os.environ.get("DB_PORT", 3306)),
        'user': os.environ.get("DB_USER", "root"),
        'password': os.environ.get("DB_PASSWORD", ""),
        'database': os.environ.get("DB_NAME", "cardioai"),
        'charset': 'utf8mb4',
        'connect_timeout': 5
    }
    conn = pymysql.connect(**DB_CONFIG)
    conn.cursorclass = pymysql.cursors.DictCursor
    return conn

def _get_sqlite_db():
    conn = sqlite3.connect(current_app.config['SQLITE_DB_PATH'])
    conn.row_factory = sqlite3.Row
    return conn

def _init_cloud_db():
    conn = _get_cloud_db()
    with conn.cursor() as cursor:
        # ... (所有 CREATE TABLE IF NOT EXISTS for MySQL 的语句) ...
        # (此处省略与 app.py 中相同的建表语句)
        cursor.execute("CREATE TABLE IF NOT EXISTS measurements (id INT AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(100) NOT NULL, sbp INT NOT NULL, dbp INT NOT NULL, hr INT DEFAULT 75, symptoms TEXT DEFAULT '[]', risk_level VARCHAR(20) DEFAULT 'normal', risk_text TEXT DEFAULT '', analysis TEXT DEFAULT '{}', datetime VARCHAR(50) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, INDEX idx_user_id (user_id), INDEX idx_datetime (datetime)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cursor.execute("CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(100) UNIQUE NOT NULL, name VARCHAR(50) DEFAULT '', age INT DEFAULT 0, gender VARCHAR(10) DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cursor.execute("CREATE TABLE IF NOT EXISTS family_bindings (id INT AUTO_INCREMENT PRIMARY KEY, family_id VARCHAR(100) NOT NULL, patient_id VARCHAR(100) NOT NULL, name VARCHAR(50) NOT NULL, status VARCHAR(20) DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY unique_binding (family_id, patient_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cursor.execute("CREATE TABLE IF NOT EXISTS feedbacks (id INT AUTO_INCREMENT PRIMARY KEY, from_id VARCHAR(100) NOT NULL, from_role VARCHAR(20) NOT NULL, to_id VARCHAR(100) NOT NULL, content TEXT NOT NULL, is_read INT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, INDEX idx_to_id (to_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cursor.execute("CREATE TABLE IF NOT EXISTS doctor_bindings (id INT AUTO_INCREMENT PRIMARY KEY, doctor_id VARCHAR(100) NOT NULL, patient_id VARCHAR(100) NOT NULL, doctor_name VARCHAR(50) DEFAULT '', hospital VARCHAR(200) DEFAULT '', department VARCHAR(100) DEFAULT '', status VARCHAR(20) DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY unique_dr_binding (doctor_id, patient_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cursor.execute("CREATE TABLE IF NOT EXISTS invite_codes (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(10) NOT NULL UNIQUE, patient_id VARCHAR(100) NOT NULL, used INT DEFAULT 0, used_by VARCHAR(100) DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMP NULL, INDEX idx_code (code), INDEX idx_patient (patient_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cursor.execute("CREATE TABLE IF NOT EXISTS invite_tokens (id INT AUTO_INCREMENT PRIMARY KEY, token VARCHAR(64) NOT NULL UNIQUE, patient_id VARCHAR(100) NOT NULL, role VARCHAR(20) NOT NULL, used INT DEFAULT 0, used_by VARCHAR(100) DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMP NULL, INDEX idx_token (token), INDEX idx_patient (patient_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        for tbl in ['family_bindings', 'doctor_bindings']:
            try:
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN status VARCHAR(20) DEFAULT 'active'")
            except Exception:
                pass
    conn.commit()
    conn.close()
    print("✅ [DB] MySQL 初始化完成", flush=True)

def _init_sqlite_db():
    conn = _get_sqlite_db()
    with conn:
        # ... (所有 CREATE TABLE IF NOT EXISTS for SQLite 的语句) ...
        # (此处省略与 app.py 中相同的建表语句)
        conn.execute("CREATE TABLE IF NOT EXISTS measurements (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, sbp INTEGER NOT NULL, dbp INTEGER NOT NULL, hr INTEGER DEFAULT 75, symptoms TEXT DEFAULT '[]', risk_level TEXT DEFAULT 'normal', risk_text TEXT DEFAULT '', analysis TEXT DEFAULT '{}', datetime TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE NOT NULL, name TEXT DEFAULT '', age INTEGER DEFAULT 0, gender TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS family_bindings (id INTEGER PRIMARY KEY AUTOINCREMENT, family_id TEXT NOT NULL, patient_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now')), UNIQUE(family_id, patient_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS feedbacks (id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT NOT NULL, from_role TEXT NOT NULL, to_id TEXT NOT NULL, content TEXT NOT NULL, is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS doctor_bindings (id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_id TEXT NOT NULL, patient_id TEXT NOT NULL, doctor_name TEXT DEFAULT '', hospital TEXT DEFAULT '', department TEXT DEFAULT '', status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now')), UNIQUE(doctor_id, patient_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS invite_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, patient_id TEXT NOT NULL, used INTEGER DEFAULT 0, used_by TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')), expires_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS invite_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE, patient_id TEXT NOT NULL, role TEXT NOT NULL, used INTEGER DEFAULT 0, used_by TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')), expires_at TEXT)")
        for tbl in ['family_bindings', 'doctor_bindings']:
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN status TEXT DEFAULT 'active'")
            except Exception:
                pass
    conn.close()
    print("✅ [DB] SQLite 初始化完成", flush=True)