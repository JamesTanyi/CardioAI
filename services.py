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
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                record["datetime"] = datetime.strptime(ts, fmt).strftime("%Y-%m-%d %H:%M:%S")
                break
            except (ValueError, TypeError):
                continue
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