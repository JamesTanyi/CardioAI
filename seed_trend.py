import sqlite3
from datetime import datetime, timedelta
conn = sqlite3.connect('bloodtrack.db')
cur = conn.cursor()
cur.execute("DELETE FROM measurements WHERE user_id='T001'")
conn.commit()
print('cleared old records')
now = datetime.now()
for i in range(20):
    dt = (now - timedelta(days=20 - i)).strftime('%Y-%m-%d %H:%M')
    sbp = int(120 + i * 1.2)
    dbp = int(78 + i * 0.4)
    hr = int(70 + i * 0.3)
    cur.execute("INSERT INTO measurements (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime) VALUES (?,?,?,?,?,?,?,?,?)", ('T001', sbp, dbp, hr, '[]', 'low', '-', '{}', dt))
conn.commit()
print('seeded 20 records, last sbp =', sbp)
