#!/usr/bin/env python
"""初始化测试数据库"""
import sqlite3

db_path = 'cardioai.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 创建表
cur.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT,
    age INTEGER,
    gender TEXT,
    role TEXT DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cur.execute('''
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    sbp INTEGER,
    dbp INTEGER,
    hr INTEGER,
    risk_level TEXT,
    datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    note TEXT
)
''')

cur.execute('''
CREATE TABLE IF NOT EXISTS family_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id TEXT,
    patient_id TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cur.execute('''
CREATE TABLE IF NOT EXISTS doctor_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id TEXT,
    patient_id TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# 创建测试患者
test_patient_id = 'P00001'
cur.execute('SELECT user_id FROM users WHERE user_id=?', (test_patient_id,))
if not cur.fetchone():
    cur.execute(
        'INSERT INTO users (user_id, name, age, gender, role) VALUES (?, ?, ?, ?, ?)',
        (test_patient_id, '测试患者', 60, 'male', 'user')
    )
    print(f'已创建测试患者: {test_patient_id}')
else:
    print(f'测试患者已存在: {test_patient_id}')

conn.commit()

# 验证
cur.execute('SELECT user_id, name FROM users')
print('数据库中的用户:', cur.fetchall())

conn.close()
print('数据库初始化完成')
