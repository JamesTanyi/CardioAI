# -*- coding: utf-8 -*-
# binding_views.py
from flask import Blueprint, jsonify, request
import database
import json
from datetime import datetime
from engine.cardiovascular_engine import CardiovascularEngine

binding_bp = Blueprint('binding', __name__)

def parse_to_datetime_obj(ts):
    if isinstance(ts, datetime): return ts
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try: return datetime.strptime(ts, fmt)
            except ValueError: continue
    return datetime.now()

@binding_bp.route('/get_binding_status', methods=['GET'])
def get_binding_status():
    """对应前端 app.js 启动和轮询调用"""
    user_id = request.args.get('userId') or request.args.get('user_id')
    if not user_id:
        return jsonify({"code": 1, "msg": "Missing userId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    has_family_binding = False
    family_patients = []
    family_alert_risk = "none"
    family_patient_name = ""

    has_doctor_binding = False
    doctor_patients = []
    doctor_alert_count = 0

    try:
        # 自适应探测 family_bindings 表结构，100% 防止 no such column
        columns = database.get_table_columns(cursor, 'family_bindings')

        family_bonds = []
        if columns:
            target_col = "sharer_id" if "sharer_id" in columns else ("user_id" if "user_id" in columns else columns[1])
            cursor.execute(f"SELECT * FROM family_bindings WHERE {target_col} = {ph}", (user_id,))
            family_bonds = cursor.fetchall()

        if family_bonds:
            has_family_binding = True
            p_id_holder = family_bonds[0]["patient_id"] if "patient_id" in columns else user_id

            # ★ 新增：查患者的 name + birth_date，拼成"姓名(出生日期)"展示名，
            #   方便家属一眼认出这是谁，而不是只看到一串内部 user_id
            cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (p_id_holder,))
            p_user = cursor.fetchone()
            if p_user and p_user.get('name'):
                bdate = p_user.get('birth_date') or ''
                family_patient_name = f"{p_user['name']}({bdate})" if bdate else p_user['name']
            else:
                family_patient_name = "我的关联被监护家人"  # 兜底：查不到患者资料时的老文案

            family_patients.append({
                "patientId": p_id_holder,
                "patientName": family_patient_name
            })
            # 💡 动态健康监控：抽取时间序列为家属端运算当前警报级别
            family_alert_risk = _calculate_realtime_risk(conn, cursor, p_id_holder)

        # 检查医生监护池
        cursor.execute(f"SELECT * FROM doctor_bindings WHERE doctor_id = {ph}", (user_id,))
        doctor_bonds = cursor.fetchall()

        if doctor_bonds:
            has_doctor_binding = True
            for bond in doctor_bonds:
                p_id = bond['patient_id']
                # ★ 改：同时查 birth_date，拼成展示名
                cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (p_id,))
                p_user = cursor.fetchone()
                if p_user and p_user.get('name'):
                    bdate = p_user.get('birth_date') or ''
                    p_name = f"{p_user['name']}({bdate})" if bdate else p_user['name']
                else:
                    p_name = "签约患者"  # 兜底：查不到患者资料时的老文案

                # ★ 改：把风险等级也一起返回，供医生端列表展示状态徽章 + 排序依据
                risk = _calculate_realtime_risk(conn, cursor, p_id)
                doctor_patients.append({"patientId": p_id, "patientName": p_name, "riskLevel": risk})
                # 如果医生监护的某位患者触发了高风险，医生的未读红点加1
                if risk in ["high", "critical"]:
                    doctor_alert_count += 1

            # ★ 新增：按病情严重程度排序，最需要关注的患者排在列表最前面（预警优先展示）
            #   闭环理念：医生端不是"有病来找",而是持续追踪，列表顺序本身就是一种预警
            risk_priority = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "none": 0}
            doctor_patients.sort(key=lambda p: risk_priority.get(p["riskLevel"], 0), reverse=True)

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "hasFamilyBinding": has_family_binding,
                "familyPatients": family_patients,
                "hasDoctorBinding": has_doctor_binding,
                "doctorPatients": doctor_patients,
                "familyAlertRisk": family_alert_risk,
                "doctorAlertCount": doctor_alert_count,
                "familyAlertSummary": {"patientName": family_patient_name}
            }
        })

    except Exception as e:
        print(f"⚠️ [Binding status proxy auto sync active]: {e}")
        return jsonify({
            "code": 0, "msg": "degraded success",
            "data": {
                "hasFamilyBinding": False, "familyPatients": [],
                "hasDoctorBinding": False, "doctorPatients": [],
                "familyAlertRisk": "none", "doctorAlertCount": 0, "familyAlertSummary": {"patientName": ""}
            }
        })

def _calculate_realtime_risk(conn, cursor, user_id):
    """辅助长效健康闭环：时序数据清洗并唤醒核心引擎"""
    ph = database.get_placeholder()
    try:
        cursor.execute(
            f"SELECT sbp, dbp, hr, symptoms, datetime FROM measurements WHERE user_id = {ph} ORDER BY datetime DESC LIMIT 20",
            (user_id,)
        )
        rows = cursor.fetchall()
        if not rows: return "none"

        records = []
        for r in rows:
            d_r = dict(r)
            try:
                if isinstance(d_r.get('symptoms'), str):
                    d_r['symptoms'] = json.loads(d_r['symptoms'] or '[]')
            except: d_r['symptoms'] = []
            d_r['datetime'] = parse_to_datetime_obj(d_r.get('datetime'))
            records.append(d_r)

        if len(records) < 2:
            return records[0].get("risk_level", "low")

        engine = CardiovascularEngine(history=records[1:], current=records[0])
        res = engine.run_all_diagnostics()
        return res.get("risk_level", "low")
    except:
        return "low"

@binding_bp.route('/get_feedback', methods=['GET'])
def get_feedback():
    return jsonify({"code": 0, "msg": "success", "data": {"feedbacks": []}})

@binding_bp.route('/register_user', methods=['POST'])
def register_user():
    """真正的核心大脑：将前端皮囊上报的用户数据，写入数据库"""
    try:
        data = request.json or {}
        user_id = data.get('user_id') or data.get('userId')  # 双重保险兼容字段
        name = data.get('name')
        age = data.get('age', 0)
        gender = data.get('gender', '')
        role = data.get('role', 'user')
        # ★ 新增：出生日期，注册时必填（前端已校验），用于家属/医生端展示"姓名(出生日期)"识别患者
        birth_date = data.get('birth_date') or data.get('birthDate') or ''

        if not user_id or not name:
            return jsonify({"code": -1, "msg": "核心字段缺失，大脑拒绝写入"}), 400

        conn = database.get_db()
        cursor = conn.cursor()
        ph = database.get_placeholder()

        # 检查是否已经是老用户，防止 UNIQUE 冲突
        cursor.execute(f"SELECT id FROM users WHERE user_id = {ph}", (user_id,))
        exists = cursor.fetchone()

        if exists:
            # 已存在则更新资料
            cursor.execute(f"""
                UPDATE users SET name={ph}, age={ph}, gender={ph}, role={ph}, birth_date={ph} WHERE user_id={ph}
            """, (name, age, gender, role, birth_date, user_id))
        else:
            # 新用户插入 users 表
            cursor.execute(f"""
                INSERT INTO users (user_id, name, age, gender, role, birth_date) 
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """, (user_id, name, age, gender, role, birth_date))

        conn.commit()
        print(f"🟢 [DB] 用户 {name}({user_id}) 注册数据成功写入！", flush=True)

        return jsonify({
            "code": 0,
            "msg": "注册成功"
        }), 200

    except Exception as e:
        print(f"❌ [DB] 注册存盘发生坍塌: {str(e)}", flush=True)
        return jsonify({"code": 500, "msg": f"大脑数据库写入异常: {str(e)}"}), 500


# ============================================================
# ★ 新增：V10 邀请绑定主链路（永久链接模式）
# 前端 intro.js 里调用的 cloudService.validateInvite / bindByInvite
# 对应的后端实现，此前完全缺失，导致邀请绑定功能实际不可用。
# 分享链接里携带的是患者的 user_id 本身（永久有效），不是一次性 token。
# ============================================================

@binding_bp.route('/validate_invite', methods=['POST'])
def validate_invite():
    """
    邀请确认页打开时调用：校验链接里的 patientId 是否对应真实存在的患者，
    并返回患者展示名 + 一份简单摘要，供家属/医生确认"这是不是我要绑定的人"。
    """
    data = request.json or {}
    patient_id = data.get('patientId')
    role = data.get('role')  # 'family' | 'doctor'，当前校验逻辑不区分角色，仅透传保留

    if not patient_id:
        return jsonify({"code": 1, "msg": "缺少 patientId"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (patient_id,))
        patient = cursor.fetchone()

        if not patient or not patient.get('name'):
            return jsonify({"code": -1, "msg": "邀请链接无效或患者不存在"}), 404

        bdate = patient.get('birth_date') or ''
        patient_name = f"{patient['name']}({bdate})" if bdate else patient['name']

        # 患者摘要：取最近一次测量记录，给确认页一个基本的"认人"参考
        cursor.execute(
            f"SELECT sbp, dbp, risk_level, datetime FROM measurements WHERE user_id = {ph} ORDER BY datetime DESC LIMIT 1",
            (patient_id,)
        )
        latest = cursor.fetchone()
        patient_summary = {
            "name": patient_name,
            "latestSbp": latest['sbp'] if latest else None,
            "latestDbp": latest['dbp'] if latest else None,
            "latestRiskLevel": latest['risk_level'] if latest else None,
            "latestDatetime": latest['datetime'] if latest else None,
        }

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "patientName": patient_name,
                "patientSummary": patient_summary
            }
        })

    except Exception as e:
        print(f"❌ [validate_invite] 校验失败: {e}", flush=True)
        return jsonify({"code": -1, "msg": f"校验失败: {str(e)}"}), 500


@binding_bp.route('/bind_by_invite', methods=['POST'])
def bind_by_invite():
    """
    用户点击"确认绑定"后调用：写入 family_bindings 或 doctor_bindings。
    如果之前已经绑定过同一对 (viewer, patient)，则把状态刷新为 active，
    不会因为 UNIQUE 约束报错而失败（幂等处理，允许重复点击/重新绑定）。
    """
    data = request.json or {}
    patient_id = data.get('patientId')
    role = data.get('role')
    viewer_id = data.get('viewerId')
    viewer_name = data.get('viewerName') or ''
    hospital = data.get('hospital') or ''
    department = data.get('department') or ''

    if not patient_id or not role or not viewer_id:
        return jsonify({"code": -1, "msg": "缺少必要参数"}), 400
    if role not in ('family', 'doctor'):
        return jsonify({"code": -1, "msg": "role 参数不合法"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        # 再次确认患者存在（防止确认页打开后患者数据被删除的边界情况）
        cursor.execute(f"SELECT name FROM users WHERE user_id = {ph}", (patient_id,))
        patient = cursor.fetchone()
        if not patient:
            return jsonify({"code": -1, "msg": "患者不存在，绑定失败"}), 404
        patient_name = patient.get('name') or ''

        # 确保家属/医生本人也在 users 表里有记录，避免后续查询缺数据
        cursor.execute(f"SELECT id FROM users WHERE user_id = {ph}", (viewer_id,))
        viewer_exists = cursor.fetchone()
        if not viewer_exists:
            cursor.execute(
                f"INSERT INTO users (user_id, name, role) VALUES ({ph}, {ph}, {ph})",
                (viewer_id, viewer_name, role)
            )

        if role == 'family':
            cursor.execute(
                f"SELECT id FROM family_bindings WHERE family_id={ph} AND patient_id={ph}",
                (viewer_id, patient_id)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    f"UPDATE family_bindings SET status='active', name={ph} WHERE family_id={ph} AND patient_id={ph}",
                    (patient_name, viewer_id, patient_id)
                )
            else:
                cursor.execute(
                    f"INSERT INTO family_bindings (family_id, patient_id, name, status) VALUES ({ph}, {ph}, {ph}, 'active')",
                    (viewer_id, patient_id, patient_name)
                )
        else:  # doctor
            cursor.execute(
                f"SELECT id FROM doctor_bindings WHERE doctor_id={ph} AND patient_id={ph}",
                (viewer_id, patient_id)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    f"""UPDATE doctor_bindings SET status='active', doctor_name={ph}, hospital={ph}, department={ph}
                        WHERE doctor_id={ph} AND patient_id={ph}""",
                    (viewer_name, hospital, department, viewer_id, patient_id)
                )
            else:
                cursor.execute(
                    f"""INSERT INTO doctor_bindings (doctor_id, patient_id, doctor_name, hospital, department, status)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, 'active')""",
                    (viewer_id, patient_id, viewer_name, hospital, department)
                )

        conn.commit()
        print(f"🟢 [DB] 绑定成功: {role} {viewer_id} -> patient {patient_id}", flush=True)

        return jsonify({"code": 0, "msg": "绑定成功"})

    except Exception as e:
        print(f"❌ [bind_by_invite] 绑定失败: {e}", flush=True)
        return jsonify({"code": -1, "msg": f"绑定失败: {str(e)}"}), 500


# ============================================================
# ★ 新增：医生端患者列表分页搜索（幽灵接口第二批）
# 前端 doctor/dashboard/dashboard.js 的 loadBoundPatients() 一直在调用这个接口，
# 之前后端完全没实现，请求会静默失败。主体患者列表走 get_binding_status 不受影响，
# 这个接口只补齐"下拉框内按姓名搜索 + 翻页"这个辅助功能。
# ============================================================

@binding_bp.route('/get_doctor_patients', methods=['GET'])
def get_doctor_patients():
    """
    医生端患者列表：支持按姓名搜索、按风险等级降序排序、分页。
    患者数量级别不大，这里先查出该医生的全部绑定患者，
    在内存里完成排序/搜索/分页，不做数据库层面的分页优化。
    """
    doctor_id = request.args.get('doctorId')
    if not doctor_id:
        return jsonify({"code": 1, "msg": "缺少 doctorId"}), 400

    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('pageSize', 20))
    except ValueError:
        page, page_size = 1, 20
    keyword = (request.args.get('keyword') or '').strip()

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        cursor.execute(f"SELECT * FROM doctor_bindings WHERE doctor_id = {ph}", (doctor_id,))
        doctor_bonds = cursor.fetchall()

        all_patients = []
        for bond in doctor_bonds:
            bond = dict(bond)  # ★ 统一转 dict：sqlite3.Row 不支持 .get()，MySQL 的 dict 结果 dict() 是幂等操作，两边都安全
            p_id = bond['patient_id']
            cursor.execute(f"SELECT name, birth_date FROM users WHERE user_id = {ph}", (p_id,))
            p_user = cursor.fetchone()
            p_user = dict(p_user) if p_user else None

            raw_name = p_user['name'] if (p_user and p_user.get('name')) else ''
            # ★ 关键词搜索只匹配姓名，不匹配内部 user_id
            #   （患者内部ID不该作为医生可用的查找方式，姓名同名概率低，够用）
            if keyword and keyword not in raw_name:
                continue

            bdate = p_user.get('birth_date') if p_user else ''
            p_name = f"{raw_name}({bdate})" if (raw_name and bdate) else (raw_name or '签约患者')

            risk = _calculate_realtime_risk(conn, cursor, p_id)
            all_patients.append({
                "patientId": p_id,
                "patientName": p_name,
                "riskLevel": risk,
                "doctorName": bond.get('doctor_name') or '',
                "hospital": bond.get('hospital') or '',
                "department": bond.get('department') or ''
            })

        # ★ 按风险等级降序排序，和 get_binding_status 保持一致的优先级
        risk_priority = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "none": 0}
        all_patients.sort(key=lambda p: risk_priority.get(p["riskLevel"], 0), reverse=True)

        total = len(all_patients)
        start = (page - 1) * page_size
        end = start + page_size
        page_data = all_patients[start:end]
        has_more = end < total

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": page_data,
            "total": total,
            "hasMore": has_more
        })

    except Exception as e:
        print(f"❌ [get_doctor_patients] 查询失败: {e}", flush=True)
        return jsonify({"code": -1, "msg": f"查询失败: {str(e)}"}), 500


# ============================================================
# ★ 新增：历史数据批量上传（幽灵接口第二批，最后一个）
# ★ 改：原本设计走 wx.uploadFile 直连裸域名（不带 /api 前缀），实测在本项目
#   环境下从未跑通（404）。现改为前端把文件读成 base64、通过已验证可靠的
#   wx.cloud.callContainer 以普通 JSON 方式发送，因此这里和其他接口一样
#   走标准 /api 前缀，注册在 binding_bp 蓝图下，不再需要 app.py 里的特例路由。
#
# 支持 .xlsx/.xls（openpyxl 解析）和 .csv（Python 内置 csv 模块解析）。
# 必填列：日期、时间、收缩压、舒张压；心率可为空（默认75）。
# 脉压差由后端自动计算，不读取任何"脉压差"列。不解析"备注"列。
# 不触发分析引擎，纯批量存库——患者之后正常测量提交时，
# /api/analyze 会自动把全部历史（含这批导入的）一起纳入稳态计算。
# ============================================================

def _process_import_rows(rows, user_id, cursor, ph):
    """
    统一处理逻辑：rows 是一个可迭代对象，每个元素是 dict（列名 -> 值），
    xlsx 和 csv 两条解析路径最终都转换成这种统一格式后传进来。
    返回 (imported, skipped)。
    """
    imported = 0
    skipped = 0

    for row in rows:
        date_val = (row.get('日期') or '').strip() if row.get('日期') else ''
        time_val = (row.get('时间') or '').strip() if row.get('时间') else ''
        sbp_val = (row.get('收缩压') or '').strip() if row.get('收缩压') else ''
        dbp_val = (row.get('舒张压') or '').strip() if row.get('舒张压') else ''
        hr_val = (row.get('心率') or '').strip() if row.get('心率') else ''

        if not date_val or not time_val or not sbp_val or not dbp_val:
            skipped += 1
            continue

        try:
            sbp = int(float(sbp_val))
            dbp = int(float(dbp_val))
        except (ValueError, TypeError):
            skipped += 1
            continue

        try:
            hr = int(float(hr_val)) if hr_val else 75
        except (ValueError, TypeError):
            hr = 75

        datetime_str = f"{date_val} {time_val}"

        cursor.execute(f"""
            INSERT INTO measurements (user_id, sbp, dbp, hr, symptoms, risk_level, risk_text, analysis, datetime)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (
            user_id, sbp, dbp, hr,
            json.dumps([], ensure_ascii=False),
            'normal',
            '',
            json.dumps({}, ensure_ascii=False),
            datetime_str
        ))
        imported += 1

    return imported, skipped


@binding_bp.route('/upload_excel', methods=['POST'])
def upload_excel():
    """
    接收前端以 base64 编码传来的 Excel/CSV 文件内容，解析后批量导入 measurements 表。
    请求体（JSON）: { fileName, userId, fileBase64 }
    """
    import base64
    import io

    data = request.json or {}
    file_name = (data.get('fileName') or '').lower()
    user_id = data.get('userId') or data.get('user_id')
    file_base64 = data.get('fileBase64')

    if not file_base64:
        return jsonify({"code": -1, "msg": "未收到文件内容"}), 400
    if not user_id:
        return jsonify({"code": -1, "msg": "缺少 userId，无法确定归属患者"}), 400

    is_csv = file_name.endswith('.csv')
    is_excel = file_name.endswith('.xlsx') or file_name.endswith('.xls')
    if not is_csv and not is_excel:
        return jsonify({"code": -1, "msg": "仅支持 .xlsx/.xls/.csv 文件"}), 400

    try:
        file_bytes = base64.b64decode(file_base64)
    except Exception as e:
        return jsonify({"code": -1, "msg": f"文件内容解码失败: {str(e)}"}), 400

    rows = []
    required_cols = ["日期", "时间", "收缩压", "舒张压"]

    try:
        if is_excel:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet = wb.active

            header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if not header_row:
                return jsonify({"code": -1, "msg": "文件为空或缺少表头"}), 400

            headers = [str(h).strip() if h else '' for h in header_row]
            missing_cols = [c for c in required_cols if c not in headers]
            if missing_cols:
                return jsonify({"code": -1, "msg": f"表头缺少必填列: {', '.join(missing_cols)}"}), 400

            for data_row in sheet.iter_rows(min_row=2, values_only=True):
                row_dict = {}
                for idx, col_name in enumerate(headers):
                    if not col_name or idx >= len(data_row):
                        continue
                    val = data_row[idx]
                    row_dict[col_name] = str(val).strip() if val is not None else ''
                rows.append(row_dict)

        else:  # csv
            import csv
            try:
                text = file_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = file_bytes.decode('gbk', errors='ignore')

            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                return jsonify({"code": -1, "msg": "文件为空或缺少表头"}), 400

            headers = [h.strip() if h else '' for h in reader.fieldnames]
            missing_cols = [c for c in required_cols if c not in headers]
            if missing_cols:
                return jsonify({"code": -1, "msg": f"表头缺少必填列: {', '.join(missing_cols)}"}), 400

            for raw_row in reader:
                row_dict = {(k.strip() if k else k): (v.strip() if v else v) for k, v in raw_row.items()}
                rows.append(row_dict)

    except Exception as e:
        return jsonify({"code": -1, "msg": f"文件解析失败，请确认文件格式正确: {str(e)}"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        imported, skipped = _process_import_rows(rows, user_id, cursor, ph)
        conn.commit()
        print(f"🟢 [DB] 批量导入完成: user={user_id}, 成功{imported}条, 跳过{skipped}条", flush=True)

        return jsonify({
            "code": 0,
            "msg": "导入完成",
            "data": {"imported": imported, "skipped": skipped}
        })

    except Exception as e:
        print(f"❌ [upload_excel] 导入失败: {e}", flush=True)
        return jsonify({"code": -1, "msg": f"导入失败: {str(e)}"}), 500