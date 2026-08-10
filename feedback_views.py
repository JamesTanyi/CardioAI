#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
三方反馈路由 (Views)

★ 重新设计：留言线从"一个患者一条共享线"改成"一个患者+一个医生一条独立线"——
一个患者如果同时绑定了多个医生（国内很常见，患者换医生很随意），医生之间
互相看不到对方跟这个患者的交流；但患者本人和家属，在这个患者名下所有医生
的留言线上都能看、都能发（共享全部信息，不受这个隔离限制）。

数据库表 feedbacks 加了 doctor_id 字段，用 (to_id, doctor_id) 这个组合
标识"这是哪个患者、跟哪个医生的那条线"。

权限模型：
- 患者本人：对自己名下任意一条(真实存在绑定的)医生线，都能查看/发送。
- 家属：对绑定患者名下任意一条(真实存在绑定的)医生线，都能查看/发送。
- 医生：只能查看/发送自己那一条线，即使对这个患者本身有 active 绑定，
  也不能查看/发送到别的医生的线——这是"医生间互相隔离"的关键校验。

删除/清空：只有患者本人能操作，家属和医生都不能删除或清空任何留言
（哪怕是自己发的也不行）。
"""

from flask import Blueprint, request, jsonify, current_app

import database
from auth import require_binding_permission

feedback_bp = Blueprint('feedback', __name__)


def _is_active_doctor_of(cursor, ph, doctor_id, patient_id):
    """某个人是不是这个患者当前 active 状态的绑定医生"""
    cursor.execute(
        f"SELECT id FROM doctor_bindings WHERE doctor_id={ph} AND patient_id={ph} AND status='active'",
        (doctor_id, patient_id)
    )
    return cursor.fetchone() is not None


def _is_active_family_of(cursor, ph, family_id, patient_id):
    """某个人是不是这个患者当前 active 状态的绑定家属"""
    cursor.execute(
        f"SELECT id FROM family_bindings WHERE family_id={ph} AND patient_id={ph} AND status='active'",
        (family_id, patient_id)
    )
    return cursor.fetchone() is not None


@feedback_bp.route("/get_relation_role", methods=["GET"])
def get_relation_role():
    """
    ★ 新增：查"我"相对于某一个具体患者，真实持有的关系角色——
    不读 users.role（这个字段只在账号第一次注册时写入，之后即使同一个
    微信账号又被邀请确认了别的角色，也不会更新，会一直冻结在最早那次），
    也不读本地缓存的 currentRole（同样的问题：只反映"最近一次冷启动时
    服务器记的角色"，不反映"我对这个具体患者到底是什么关系"）。

    现实中一个微信账号完全可能同时是患者A的家属、又是患者B的医生——
    "我是什么角色"这件事本来就不该是一个全局唯一值，只有绑定关系表
    (family_bindings/doctor_bindings)才是权威数据源，所以直接查这两张表，
    以"针对这一个患者"为准。feedback.js 用这个接口判断角色，而不是
    自己猜 currentRole，避免账号身兼多重身份时把角色/留言线认错。
    """
    patient_id = request.args.get("patientId")
    viewer_id = request.args.get("viewerId")

    if not patient_id or not viewer_id:
        return jsonify({"code": 1, "error": "缺少 patientId/viewerId 参数"}), 400

    if viewer_id == patient_id:
        return jsonify({"code": 0, "data": {"role": "patient"}})

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        # 医生身份优先判断——如果这个账号同时也挂着这个患者的家属关系
        # (比如很早以前测试/使用留下的)，医生身份仍然优先生效，保证
        # "我是这条线本身的医生"这件事不会被别的关系覆盖
        if _is_active_doctor_of(cursor, ph, viewer_id, patient_id):
            return jsonify({"code": 0, "data": {"role": "doctor"}})
        if _is_active_family_of(cursor, ph, viewer_id, patient_id):
            return jsonify({"code": 0, "data": {"role": "family"}})
        return jsonify({"code": 0, "data": {"role": "none"}})
    except Exception as e:
        return jsonify({"code": 1, "error": "查询失败", "detail": str(e)}), 500


@feedback_bp.route("/get_feedback", methods=["GET"])
@require_binding_permission
def get_feedback():
    """
    获取"某个患者 + 某条线"的留言（按最新时间排在最前面）。

    ★ 改：doctorId 不再是必填参数——不传/传空字符串，代表"基础线"
    （患者+家属专属，永远存在，不挂任何医生，医生完全无法访问）；
    传具体的医生 id，代表"诊疗线"（患者+家属+这位医生三方共享，
    医生之间互相隔离，跟之前设计一致）。
    doctor_id 在数据库里统一用空字符串 '' 表示基础线，不用 NULL——
    NULL 参与 feedback_read_progress 表的唯一性判断时，大多数数据库
    会把它当成"永远不算重复"，导致已读记录机制失效，用 '' 完全没有这个问题。

    require_binding_permission 装饰器已经验证过 viewerId 对 userId(=patientId) 有权限
    （这一步只确认"viewer 跟这个患者有关系"，还不够——医生还要额外确认
    只能看自己那条线，基础线还要额外确认医生完全不能进，见下面的补充校验）。
    """
    patient_id = request.args.get("userId") or request.args.get("user_id")
    viewer_id = request.args.get("viewerId")
    doctor_id = request.args.get("doctorId") or ""

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        if doctor_id == "":
            # ★ 基础线：只有患者本人和绑定家属能访问，医生完全无权限——
            #   哪怕这个人同时也是该患者的绑定医生，也不能靠这层关系看到
            #   患者和家属之间的私下交流，这是这次架构调整的核心诉求
            if viewer_id and viewer_id != patient_id:
                if _is_active_doctor_of(cursor, ph, viewer_id, patient_id):
                    return jsonify({"code": 1, "error": "医生无权限查看基础对话线"}), 403
                if not _is_active_family_of(cursor, ph, viewer_id, patient_id):
                    return jsonify({"code": 1, "error": "无权限查看该基础对话线"}), 403
        else:
            # ★ 诊疗线：关键校验——如果查看者本人就是这个患者的一个绑定医生，
            #   那他只能看自己这条线，不能靠"对这个患者本身有权限"就看别的医生的线
            if viewer_id and viewer_id != patient_id:
                if _is_active_doctor_of(cursor, ph, viewer_id, patient_id) and viewer_id != doctor_id:
                    return jsonify({"code": 1, "error": "无权限查看其他医生的留言线"}), 403

        # ★ 改：加 JOIN users 表把发言人的真实姓名一起查出来——之前只返回
        #   from_role(patient/family/doctor)，前端只能显示笼统的角色标签，
        #   同一患者绑了不止一位家属/医生时，根本分不清"家属"这个标签
        #   具体是哪一位发的。
        cursor.execute(
            f"SELECT f.id, f.from_id, f.from_role, f.content, f.is_read, f.created_at, "
            f"u.name AS sender_name "
            f"FROM feedbacks f LEFT JOIN users u ON u.user_id = f.from_id "
            f"WHERE f.to_id = {ph} AND f.doctor_id = {ph} ORDER BY f.created_at DESC",
            (patient_id, doctor_id)
        )
        rows = cursor.fetchall()
        feedbacks = [dict(row) for row in rows]
        return jsonify({"code": 0, "data": feedbacks})
    except Exception as e:
        return jsonify({"code": 1, "error": "查询失败", "detail": str(e)}), 500


@feedback_bp.route("/send_feedback", methods=["POST"])
def send_feedback():
    """
    发一条留言到"某个患者 + 某条线"。

    ★ 改：doctorId 不再必填——不传/传空字符串代表发到基础线（患者+家属专属）；
    传具体医生 id 代表发到那位医生的诊疗线。基础线场景下医生天然发不进来：
    医生账号既不等于 patient_id，通常也不是这个患者的绑定家属，会自然落到
    下面 else 分支被拒绝，不需要为"禁止医生发基础线"单独加一条校验。

    ★ 说明：这里没有用 require_binding_permission 装饰器——它是按 GET 参数
    (userId/viewerId) 校验的，而这里是 POST body，权限校验逻辑手动内联一份，
    判断标准跟 auth.py 一致，只是参数来源不同，不是另一套权限规则。
    """
    data = request.get_json(force=True) or {}
    from_id = data.get("fromId")
    from_role = data.get("fromRole")
    patient_id = data.get("patientId") or data.get("toId")
    doctor_id = data.get("doctorId") or ""
    content = (data.get("content") or "").strip()

    if not from_id or not patient_id or not content:
        return jsonify({"code": 1, "error": "缺少必要参数(fromId/patientId/content)"}), 400
    if len(content) > 500:
        return jsonify({"code": 1, "error": "内容不能超过500字"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        if doctor_id:
            # 诊疗线：doctor_id 本身必须是这个患者真实、当前有效的绑定医生，
            # 不能凭空发到一个没有真实绑定关系的"线"上
            if not _is_active_doctor_of(cursor, ph, doctor_id, patient_id):
                return jsonify({"code": 1, "error": "该医生未绑定此患者，无法发送到这条留言线"}), 403

        if from_id == patient_id:
            from_role = "patient"
        elif doctor_id and from_id == doctor_id:
            from_role = "doctor"
        elif _is_active_family_of(cursor, ph, from_id, patient_id):
            from_role = "family"
        else:
            # 剩下的情况：既不是患者本人、不是这条线对应的医生、也不是家属
            # （比如另一个医生想发到不属于自己的线，或者任何人想发到基础线
            #  但既不是患者也不是家属）——一律拒绝
            return jsonify({"code": 1, "error": "无权限给该患者留言，请先确认绑定"}), 403
    except Exception as e:
        return jsonify({"code": 1, "error": "权限校验失败", "detail": str(e)}), 500

    try:
        cursor.execute(
            f"INSERT INTO feedbacks (from_id, from_role, to_id, doctor_id, content) "
            f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph})",
            (from_id, from_role, patient_id, doctor_id, content)
        )
        conn.commit()
        return jsonify({"code": 0, "message": "发送成功"})
    except Exception as e:
        return jsonify({"code": 1, "error": "发送失败", "detail": str(e)}), 500


@feedback_bp.route("/mark_feedback_read", methods=["POST"])
def mark_feedback_read():
    """
    记录"这个查看者刚刚看过这个患者+这条线"——各端、各条线独立记录，
    不影响其他人/其他线的未读状态。

    ★ 改：doctorId 不再必填，不传/空字符串代表基础线的已读记录。
    """
    data = request.get_json(force=True) or {}
    viewer_id = data.get("viewerId")
    patient_id = data.get("patientId")
    doctor_id = data.get("doctorId") or ""

    if not viewer_id or not patient_id:
        return jsonify({"code": 1, "error": "缺少必要参数(viewerId/patientId)"}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        if current_app.config['USE_CLOUD_DB']:
            cursor.execute(
                f"INSERT INTO feedback_read_progress (viewer_id, patient_id, doctor_id, last_read_at) "
                f"VALUES ({ph}, {ph}, {ph}, CURRENT_TIMESTAMP) "
                f"ON DUPLICATE KEY UPDATE last_read_at = CURRENT_TIMESTAMP",
                (viewer_id, patient_id, doctor_id)
            )
        else:
            cursor.execute(
                f"INSERT INTO feedback_read_progress (viewer_id, patient_id, doctor_id, last_read_at) "
                f"VALUES ({ph}, {ph}, {ph}, datetime('now')) "
                f"ON CONFLICT(viewer_id, patient_id, doctor_id) DO UPDATE SET last_read_at = datetime('now')",
                (viewer_id, patient_id, doctor_id)
            )
        conn.commit()
        return jsonify({"code": 0})
    except Exception as e:
        return jsonify({"code": 1, "error": "更新已读状态失败", "detail": str(e)}), 500


@feedback_bp.route("/delete_feedback", methods=["POST"])
def delete_feedback():
    """
    删除一条或多条留言——只有患者本人能操作（家属、医生都不能删除，
    哪怕是自己发的也不行）。可以一次删多条(前端传一个 id 数组，单条也是长度为1的数组)。
    """
    data = request.get_json(force=True) or {}
    viewer_id = data.get("viewerId")
    patient_id = data.get("patientId")
    feedback_ids = data.get("feedbackIds")

    if not viewer_id or not patient_id or not feedback_ids or not isinstance(feedback_ids, list):
        return jsonify({"code": 1, "error": "缺少必要参数(viewerId/patientId/feedbackIds)"}), 400

    if viewer_id != patient_id:
        return jsonify({"code": 1, "error": "只有患者本人可以删除留言"}), 403

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        placeholders = ",".join([ph] * len(feedback_ids))
        # 加 to_id = patient_id 这层限制：只能删自己名下的留言，
        # 不能靠猜 id 删到别的患者名下的记录
        cursor.execute(
            f"DELETE FROM feedbacks WHERE id IN ({placeholders}) AND to_id = {ph}",
            (*feedback_ids, patient_id)
        )
        deleted = cursor.rowcount
        conn.commit()
        return jsonify({"code": 0, "message": f"已删除 {deleted} 条留言", "deleted_count": deleted})
    except Exception as e:
        return jsonify({"code": 1, "error": "删除失败", "detail": str(e)}), 500


@feedback_bp.route("/clear_feedback", methods=["POST"])
def clear_feedback():
    """
    清空这个患者名下、全部医生留言线的全部留言——只有患者本人能操作。
    """
    data = request.get_json(force=True) or {}
    viewer_id = data.get("viewerId")
    patient_id = data.get("patientId")

    if not viewer_id or not patient_id:
        return jsonify({"code": 1, "error": "缺少必要参数(viewerId/patientId)"}), 400

    if viewer_id != patient_id:
        return jsonify({"code": 1, "error": "只有患者本人可以清空留言"}), 403

    conn = database.get_db()
    cursor = conn.cursor()
    ph = database.get_placeholder()

    try:
        cursor.execute(f"DELETE FROM feedbacks WHERE to_id = {ph}", (patient_id,))
        deleted = cursor.rowcount
        conn.commit()
        return jsonify({"code": 0, "message": f"已清空 {deleted} 条留言", "deleted_count": deleted})
    except Exception as e:
        return jsonify({"code": 1, "error": "清空失败", "detail": str(e)}), 500