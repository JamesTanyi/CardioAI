#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库完善脚本 - 用于初始化数据库结构和添加测试数据
"""

import sqlite3
import json
from datetime import datetime, timedelta
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bloodtrack.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """初始化并完善数据库表结构"""
    conn = get_db()
    cursor = conn.cursor()
    
    print(f"📂 数据库路径: {DB_PATH}")
    
    # 1. measurements 表（如果缺少字段则添加）
    cursor.execute("""
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
    print("✅ measurements 表已创建/存在")
    
    # 2. users 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT UNIQUE NOT NULL,
            name        TEXT DEFAULT '',
            age         INTEGER DEFAULT 0,
            gender      TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    print("✅ users 表已创建/存在")
    
    # 3. family_bindings 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_bindings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id   TEXT NOT NULL,
            patient_id  TEXT NOT NULL,
            name        TEXT NOT NULL,
            status      TEXT DEFAULT 'active',
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(family_id, patient_id)
        )
    """)
    print("✅ family_bindings 表已创建/存在")
    
    # 4. feedbacks 表
    cursor.execute("""
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
    print("✅ feedbacks 表已创建/存在")
    
    conn.commit()
    
    # 5. 检查并添加缺失的字段 + 补全缺失的表
    try:
        cursor.execute("PRAGMA table_info(measurements)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'pp' not in columns:
            cursor.execute("ALTER TABLE measurements ADD COLUMN pp INTEGER DEFAULT 0")
            print("➕ 添加 pp 字段")
        
        if 'symptoms' not in columns:
            cursor.execute("ALTER TABLE measurements ADD COLUMN symptoms TEXT DEFAULT '[]'")
            print("➕ 添加 symptoms 字段")
            
    except Exception as e:
        print(f"⚠️ 检查字段时出错: {e}")

    # ★ v8：补全 doctor_bindings 和 invite_codes 表（旧版脚本缺失）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_bindings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id   TEXT NOT NULL,
            patient_id  TEXT NOT NULL,
            doctor_name TEXT DEFAULT '',
            hospital    TEXT DEFAULT '',
            department  TEXT DEFAULT '',
            status      TEXT DEFAULT 'active',
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(doctor_id, patient_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL UNIQUE,
            patient_id  TEXT NOT NULL,
            used        INTEGER DEFAULT 0,
            used_by     TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now')),
            expires_at  TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_tokens (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            token       TEXT NOT NULL UNIQUE,
            patient_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            used        INTEGER DEFAULT 0,
            used_by     TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now')),
            expires_at  TEXT
        )
    """)

    # ★ v8：为存量绑定表添加 status 字段
    for tbl in ['family_bindings', 'doctor_bindings']:
        try:
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN status TEXT DEFAULT 'active'")
            print(f"➕ 为 {tbl} 添加 status 字段")
        except Exception:
            pass  # 字段已存在
    
    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成\n")

def add_test_data():
    """添加测试数据（可选）"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 检查是否已有数据
    cursor.execute("SELECT COUNT(*) as count FROM measurements")
    count = cursor.fetchone()['count']
    
    if count > 0:
        print(f"📊 已有 {count} 条测量记录，跳过测试数据添加")
        conn.close()
        return
    
    print("📝 添加测试数据...")
    
    user_id = "谭毅1953-10-15"
    
    # 添加用户
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, name, age, gender)
        VALUES (?, ?, ?, ?)
    """, (user_id, "谭毅", 72, "男"))
    
    # 添加 30 天的测试数据
    now = datetime.now()
    for i in range(30):
        date = now - timedelta(days=i)
        datetime_str = date.strftime("%Y-%m-%d %H:%M:%S")
        
        # 模拟血压数据（逐渐改善）
        sbp = 140 - i * 0.3 + (i % 3) * 2
        dbp = 90 - i * 0.2 + (i % 3)
        hr = 75 + (i % 5)
        pp = int(sbp - dbp)
        
        risk_level = "normal" if sbp < 140 and dbp < 90 else "high"
        
        cursor.execute("""
            INSERT INTO measurements 
                (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            int(sbp), int(dbp), int(hr),
            json.dumps([]),
            risk_level,
            "正常" if risk_level == "normal" else "偏高",
            json.dumps({}),
            datetime_str
        ))
    
    conn.commit()
    print(f"✅ 已添加 30 条测试数据")
    
    # 验证
    cursor.execute("SELECT COUNT(*) as count FROM measurements")
    count = cursor.fetchone()['count']
    print(f"📊 数据库现在共有 {count} 条测量记录")
    
    conn.close()

def add_e2e_test_users():
    """添加端到端测试脚本所需的用户"""
    conn = get_db()
    cursor = conn.cursor()
    
    users_to_add = [
        ("E2E_PATIENT_张三_19581015", "E2E患者-张三", 65, "男"),
        ("E2E_FAMILY_MEMBER", "E2E家属", 35, "女"),
        ("E2E_DOCTOR_王医生", "E2E医生-王", 40, "男")
    ]
    
    for user_id, name, age, gender in users_to_add:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, name, age, gender) VALUES (?, ?, ?, ?)",
                       (user_id, name, age, gender))
    
    conn.commit()
    conn.close()
    print("✅ E2E 测试用户已添加/更新")

def add_bulk_doctor_bindings(doctor_id="E2E_DOCTOR_ID", num_patients=150):
    """为医生批量添加绑定患者，用于测试分页"""
    conn = get_db()
    cursor = conn.cursor()

    # 检查医生是否已存在
    cursor.execute("SELECT COUNT(*) as count FROM doctor_bindings WHERE doctor_id=?", (doctor_id,))
    if cursor.fetchone()['count'] >= num_patients:
        print(f"🩺 医生 {doctor_id} 已绑定足够数量的患者，跳过批量数据添加")
        conn.close()
        return

    print(f"📝 正在为医生 {doctor_id} 批量添加 {num_patients} 个绑定患者...")

    # 1. 创建医生用户
    cursor.execute("INSERT OR IGNORE INTO users (user_id, name, age, gender) VALUES (?, ?, ?, ?)",
                   (doctor_id, "分页测试医生", 45, "女"))

    # 2. 批量创建患者并绑定
    for i in range(num_patients):
        patient_id = f"BULK_PATIENT_{i}"
        
        # 创建患者用户
        cursor.execute("INSERT OR IGNORE INTO users (user_id, name, age, gender) VALUES (?, ?, ?, ?)",
                       (patient_id, f"患者{i}", 60 + i % 20, "男" if i % 2 == 0 else "女"))
        
        # 创建绑定关系
        cursor.execute("""
            INSERT OR IGNORE INTO doctor_bindings (doctor_id, patient_id, doctor_name, status)
            VALUES (?, ?, ?, 'active')
        """, (doctor_id, patient_id, "分页测试医生"))

        # 3. 为部分患者添加测量数据
        if i % 3 == 0:
            cursor.execute("INSERT OR IGNORE INTO measurements (user_id, sbp, dbp, datetime) VALUES (?, ?, ?, ?)",
                           (patient_id, 140 + i % 20, 90 + i % 10, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()
    print(f"✅ 批量添加完成")

def show_stats():
    """显示数据库统计信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    print("\n📊 数据库统计信息:")
    print("=" * 50)
    
    # measurements 统计
    cursor.execute("SELECT COUNT(*) as count FROM measurements")
    print(f"📝 测量记录: {cursor.fetchone()['count']} 条")
    
    # users 统计
    cursor.execute("SELECT COUNT(*) as count FROM users")
    print(f"👤 用户数量: {cursor.fetchone()['count']} 个")
    
    # family_bindings 统计
    cursor.execute("SELECT COUNT(*) as count FROM family_bindings")
    print(f"👨‍👩‍👧 家人绑定: {cursor.fetchone()['count']} 个")
    
    # feedbacks 统计
    cursor.execute("SELECT COUNT(*) as count FROM feedbacks")
    print(f"💬 反馈记录: {cursor.fetchone()['count']} 条")
    
    # 最近 5 条记录
    cursor.execute("""
        SELECT user_id, sbp, dbp, datetime 
        FROM measurements 
        ORDER BY datetime DESC 
        LIMIT 5
    """)
    rows = cursor.fetchall()
    if rows:
        print("\n📋 最近 5 条记录:")
        for row in rows:
            print(f"  {row['datetime']} | {row['user_id']} | {row['sbp']}/{row['dbp']} mmHg")
    
    conn.close()

if __name__ == "__main__":
    print("=" * 50)
    print("🔧 数据库完善脚本")
    print("=" * 50)
    
    # 1. 初始化数据库
    init_database()
    
    # 2. 添加测试数据
    add_test_data()
    
    # 2.1 添加 E2E 测试所需的用户
    add_e2e_test_users()

    # 2.1 添加用于分页测试的批量数据
    add_bulk_doctor_bindings()

    # 3. 显示统计信息
    show_stats()
    
    print("\n✅ 数据库完善完成！")
