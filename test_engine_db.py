# -*- coding: utf-8 -*-
"""
终端测试脚本 V2：加入严格的 datetime 对象转换清洗
"""
import sqlite3
import json
import os
from datetime import datetime

# ==========================================
# 1. 自动对齐引擎导入路径
# ==========================================
try:
    from cardiovascular_engine import CardiovascularEngine
    print("✅ 成功直接导入 CardiovascularEngine")
except ImportError:
    try:
        from engine.cardiovascular_engine import CardiovascularEngine
        print("✅ 成功通过 engine 目录导入 CardiovascularEngine")
    except ImportError as e:
        print(f"❌ 导入引擎失败，请检查文件位置！错误: {e}")
        exit(1)

# ==========================================
# 2. 核心清洗工具：把字符串时间规范化转为真正的 datetime 对象
# ==========================================
def parse_to_datetime_obj(ts):
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        # 支持各种常见的时间字符串格式
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
    return datetime.now() # 兜底

# ==========================================
# 3. 连接本地 SQLite 数据库
# ==========================================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bloodtrack.db")
print(f"📂 正在连接数据库: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row  
cursor = conn.cursor()

TEST_USER_ID = "UMR9KYBS0GIJQMF" 

print(f"🔍 正在从 measurements 表捞取用户 [{TEST_USER_ID}] 的历史时间序列...")
try:
    cursor.execute("""
        SELECT sbp, dbp, hr, symptoms, datetime 
        FROM measurements 
        WHERE user_id = ? 
        ORDER BY datetime DESC 
        LIMIT 20
    """, (TEST_USER_ID,))
    rows = cursor.fetchall()
except sqlite3.OperationalError as e:
    print(f"❌ 数据库查询失败: {e}")
    conn.close()
    exit(1)

# ==========================================
# 4. 数据格式归一化与清洗（彻底解决 'str' has no attribute 'time'）
# ==========================================
db_records = []
for r in rows:
    item = dict(r)
    # 转换 1：症状转 List
    try:
        if isinstance(item.get('symptoms'), str):
            item['symptoms'] = json.loads(item['symptoms'] or '[]')
    except Exception:
        item['symptoms'] = []
    
    # 🔥 核心修正：必须把时间字符串转化为真正的 Python datetime 对象！
    item['datetime'] = parse_to_datetime_obj(item.get('datetime'))
    db_records.append(item)

print(f"📊 成功从本地数据库捞出 {len(db_records)} 条历史记录。")

# ==========================================
# 5. 分离或构造“历史基线”与“当前测量”
# ==========================================
if len(db_records) >= 2:
    mock_current = db_records[0]
    mock_history = db_records[1:]
    print("💡 模式：使用数据库内真实的记录流进行时间序列基线评估。")
else:
    print("💡 模式：数据库记录稀少，注入人工构造的‘突发急性高血压’进行压力测试。")
    mock_history = db_records  
    
    # 🔥 人工数据的时间也必须是真实的 datetime 对象！
    mock_current = {
        "sbp": 175,
        "dbp": 110,
        "hr": 95,
        "symptoms": ["chest_pain", "dizzy"], 
        "datetime": parse_to_datetime_obj("2026-07-07 20:00")
    }

# ==========================================
# 6. 唤醒核心灵魂：运行心血管动态变化趋势引擎
# ==========================================
print("\n🧠 正在将清洗后的时间序列注入 CardiovascularEngine ...")
try:
    engine = CardiovascularEngine(history=mock_history, current=mock_current)
    result = engine.run_all_diagnostics()
    
    # ==========================================
    # 7. 终端肉眼观测核心产物
    # ==========================================
    print("\n" + "="*50)
    print("🎉 灵魂打通！核心大脑全套时序诊断分析全部通过！测试报告如下：")
    print("="*50)
    print(f"🚨 动态急性预警级别 (risk_level) : {result.get('risk_level')}")
    print(f"💬 核心引导语 (message)          : {result.get('message')}")
    
    details = result.get('details', {})
    reports = details.get('reports', {})
    
    print("\n👤 【患者本人端(User)报告摘要】:")
    print(reports.get('user', '未生成'))
    
    print("\n👨‍👩‍👧 【家属监护端(Watcher)长效安心报告】:")
    print(reports.get('watcher', '未生成'))
    
    print("\n👨‍⚕️ 【临床医生端(Doctor)结构化病历看盘】:")
    print(reports.get('doctor', '未生成'))
    print("="*50)

except Exception as engine_err:
    import traceback
    print(f"❌ 核心引擎内部运行时崩溃！详细错误堆栈如下:")
    traceback.print_exc()

finally:
    conn.close()
    print("\n🔒 数据库连接已安全关闭。测试结束。")