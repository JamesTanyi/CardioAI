import sqlite3, json
conn = sqlite3.connect('bloodtrack.db')
cur = conn.cursor()
cur.execute(
    'INSERT OR REPLACE INTO users (user_id, name, age, gender, role, birth_date, openid, health_history) VALUES (?,?,?,?,?,?,?,?)',
    ('T001', '陈测试', 66, '男', 'user', '1960-05-24', 'TEST_OPENID_T001', json.dumps(['高血压','心肌梗死'], ensure_ascii=False))
)
conn.commit()
print('T001 done')
