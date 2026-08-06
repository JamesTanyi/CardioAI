#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Application Services

This module contains shared business logic functions that can be used by different views.
"""

from datetime import datetime

def _format_record_for_db(record):
    """
    Normalizes a record and prepares it for database insertion.
    """
    ts = record.get("datetime") or record.get("timestamp") or record.get("date")
    if isinstance(ts, str):
        # ★ 改：补充更多兜底格式——这个函数现在也会被"上传历史数据"那条批量导入路径调用，
        #   Excel 表格里用户手填的日期五花八门(补零/不补零、横线/斜杠/句点分隔都可能出现)，
        #   %Y-%m-%d 和 %Y/%m/%d 这两种写法 Python 的 strptime 本身就能兼容补零与否，
        #   这里额外加上句点分隔这种少见但可能出现的写法，尽量兜住更多真实场景。
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
            try:
                record["datetime"] = datetime.strptime(ts, fmt).strftime("%Y-%m-%d %H:%M:%S")
                break
            except (ValueError, TypeError):
                continue
        else:
            # ★ 新增：所有已知格式都匹配失败——之前这里会静默保留原始字符串存进库，
            #   就是这次"上传历史数据日期格式混乱"问题被隐藏了很久都没发现的原因之一。
            #   打印警告，至少能在运行日志里第一时间看到，不再是无声无息地存进一条
            #   格式不一致的脏数据。
            print(f"⚠️ [_format_record_for_db] 日期格式无法识别，原样保留: {ts!r}", flush=True)
    elif isinstance(ts, datetime):
        record["datetime"] = ts.strftime("%Y-%m-%d %H:%M:%S")

    if "datetime" not in record or not record["datetime"]:
        record["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "user_id": record.get("userId") or record.get("user_id"),
        "sbp": int(record.get("sbp", 0)),
        "dbp": int(record.get("dbp", 0)),
        "hr": int(record.get("hr", 70)),
        "datetime": record["datetime"],
    }

def save_measurement(conn, cursor, record):
    """
    Saves a single measurement record to the database.
    """
    db_record = _format_record_for_db(record)
    if not all([db_record["user_id"], db_record["sbp"], db_record["dbp"], db_record["datetime"]]):
        raise ValueError("Record is missing required fields (userId, sbp, dbp, datetime)")

    USE_CLOUD_DB = conn.__class__.__module__.startswith('pymysql')
    sql = "INSERT INTO measurements (user_id, sbp, dbp, hr, datetime) VALUES (%s, %s, %s, %s, %s)" if USE_CLOUD_DB else "INSERT INTO measurements (user_id, sbp, dbp, hr, datetime) VALUES (?, ?, ?, ?, ?)"
    params = (db_record["user_id"], db_record["sbp"], db_record["dbp"], db_record["hr"], db_record["datetime"])
    cursor.execute(sql, params)