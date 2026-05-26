"""Operational route handlers extracted from the admin routes god-file."""
from __future__ import annotations

import os

from flask import flash, redirect, render_template, request, url_for

from services.admin.audit import log_action
from services.admin.db import get_conn
from services.admin.routes_shared import admin_ip, admin_user_id, sync_default_content_and_plans


def audit_log():
    action_filter = (request.args.get("action") or "").strip()
    entity_filter = (request.args.get("entity_type") or "").strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        where = ["1=1"]
        params = []
        if action_filter:
            where.append("action = %s")
            params.append(action_filter)
        if entity_filter:
            where.append("details ->> 'entity_type' = %s")
            params.append(entity_filter)
        where_sql = " AND ".join(where)
        cur.execute(
            f"""
            SELECT id, action, admin_user, target, details, created_at
            FROM admin_audit_log
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT 300
            """,
            params,
        )
        raw_rows = cur.fetchall()
        rows = []
        for row in raw_rows:
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            target = row.get("target")
            entity_type_value = details.get("entity_type")
            entity_id_value = details.get("entity_id")
            if not entity_type_value and isinstance(target, str) and ":" in target:
                entity_type_value, entity_id_value = target.split(":", 1)
            elif not entity_id_value:
                entity_id_value = target
            rows.append(
                {
                    "id": row.get("id"),
                    "action": row.get("action"),
                    "entity_type": entity_type_value,
                    "entity_id": entity_id_value,
                    "ip": details.get("ip"),
                    "created_at": row.get("created_at"),
                    "admin_login": row.get("admin_user"),
                    "admin_role": details.get("admin_role"),
                    "details": details or None,
                }
            )
        return render_template("audit.html", rows=rows, action_filter=action_filter, entity_filter=entity_filter)
    finally:
        conn.close()


def feedback_list():
    status_filter = (request.args.get("status") or "").strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        where = "1=1"
        params = []
        if status_filter:
            where += " AND f.status = %s"
            params.append(status_filter)
        cur.execute(
            f"""
            SELECT f.id, f.user_id, f.text, f.status, f.admin_note, f.created_at, f.updated_at, f.resolved_at,
                   u.username, u.first_name
            FROM feedback f
            LEFT JOIN users u ON u.id = f.user_id
            WHERE {where}
            ORDER BY CASE f.status WHEN 'new' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, f.created_at DESC
            LIMIT 300
            """,
            params,
        )
        rows = cur.fetchall()
        return render_template("feedback.html", rows=rows, status_filter=status_filter)
    finally:
        conn.close()


def feedback_action(feedback_id: int):
    action = (request.form.get("action") or "").strip()
    admin_note = (request.form.get("admin_note") or "").strip()[:2000]
    status = (request.form.get("status") or "").strip()
    allowed = {"new", "in_progress", "resolved", "closed"}
    conn = get_conn()
    try:
        cur = conn.cursor()
        if action == "update":
            if status not in allowed:
                flash("Неверный статус", "error")
                return redirect(url_for("feedback_list"))
            resolved_at = "NOW()" if status in {"resolved", "closed"} else "NULL"
            cur.execute(
                f"""
                UPDATE feedback
                SET status = %s,
                    admin_note = %s,
                    handled_by = %s,
                    updated_at = NOW(),
                    resolved_at = {resolved_at}
                WHERE id = %s
                """,
                (status, admin_note or None, admin_user_id(), feedback_id),
            )
            conn.commit()
            log_action("feedback_update", entity_type="feedback", entity_id=feedback_id, details={"status": status}, ip=admin_ip())
            flash("Обращение обновлено")
    finally:
        conn.close()
    return redirect(request.referrer or url_for("feedback_list"))


def content_texts():
    conn = get_conn()
    try:
        cur = conn.cursor()
        sync_default_content_and_plans(cur, admin_user_id())
        if request.method == "POST":
            key = (request.form.get("key") or "").strip()
            value = (request.form.get("value") or "").strip()
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            enabled = request.form.get("enabled") == "on"
            if key and value:
                cur.execute(
                    """
                    INSERT INTO admin_texts (key, title, description, value, enabled, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        value = EXCLUDED.value,
                        enabled = EXCLUDED.enabled,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """,
                    (key, title or key, description or None, value, enabled, admin_user_id()),
                )
                conn.commit()
                log_action("content_update", entity_type="admin_text", entity_id=key, ip=admin_ip())
                flash("Текст обновлён")
        cur.execute("SELECT key, title, description, value, enabled, updated_at FROM admin_texts ORDER BY key ASC")
        rows = cur.fetchall()
        return render_template("content.html", rows=rows)
    finally:
        conn.close()


def tariffs_list():
    conn = get_conn()
    try:
        cur = conn.cursor()
        sync_default_content_and_plans(cur, admin_user_id())
        if request.method == "POST":
            plan_key = (request.form.get("plan_key") or "").strip()
            if plan_key:
                cur.execute(
                    """
                    UPDATE billing_plans
                    SET label = %s,
                        credits = %s,
                        price_rub = %s,
                        price_stars = %s,
                        price_usd = %s,
                        discount = %s,
                        enabled = %s,
                        sort_order = %s,
                        is_one_time = %s,
                        period_days = %s,
                        updated_at = NOW()
                    WHERE plan_key = %s
                    """,
                    (
                        (request.form.get("label") or "").strip() or plan_key,
                        int(request.form.get("credits") or 0),
                        float(request.form.get("price_rub") or 0),
                        int(request.form.get("price_stars") or 0),
                        float(request.form.get("price_usd") or 0),
                        (request.form.get("discount") or "").strip(),
                        request.form.get("enabled") == "on",
                        int(request.form.get("sort_order") or 100),
                        request.form.get("is_one_time") == "on",
                        int(request.form.get("period_days") or 0) or None,
                        plan_key,
                    ),
                )
                conn.commit()
                log_action("tariff_update", entity_type="billing_plan", entity_id=plan_key, ip=admin_ip())
                flash("Тариф обновлён")
        cur.execute(
            """
            SELECT plan_key, label, credits, price_rub, price_stars, price_usd, discount,
                   enabled, sort_order, is_one_time, is_unlimited, period_days, updated_at
            FROM billing_plans
            ORDER BY sort_order ASC, plan_key ASC
            """
        )
        rows = cur.fetchall()
        return render_template("tariffs.html", rows=rows)
    finally:
        conn.close()


def user_action(user_id):
    action = request.form.get("action")
    conn = get_conn()
    try:
        cur = conn.cursor()
        if action == "ban":
            cur.execute("UPDATE users SET is_blocked = TRUE WHERE id = %s", (user_id,))
            conn.commit()
            log_action("user_block", entity_id=user_id, ip=admin_ip())
            flash("Пользователь заблокирован")
        elif action == "unban":
            cur.execute("UPDATE users SET is_blocked = FALSE WHERE id = %s", (user_id,))
            conn.commit()
            log_action("user_unblock", entity_id=user_id, ip=admin_ip())
            flash("Пользователь разблокирован")
        elif action == "add_credits":
            amount = request.form.get("amount")
            try:
                amount = int(amount)
                if amount > 0:
                    cur.execute("UPDATE users SET credits_bought = COALESCE(credits_bought, 0) + %s WHERE id = %s", (amount, user_id))
                    cur.execute(
                        "INSERT INTO credit_transactions (user_id, amount, credits_bought_after, credits_free_after, type, description) SELECT %s, %s, credits_bought, credits_free_today, 'admin_add', 'Начислено из веб-админки' FROM users WHERE id = %s",
                        (user_id, amount, user_id),
                    )
                    conn.commit()
                    log_action("credits_add", entity_id=user_id, details={"amount": amount}, ip=admin_ip())
                    flash(f"Начислено {amount} CR")
            except (ValueError, TypeError):
                flash("Неверное количество", "error")
        elif action == "sub_credits":
            amount = request.form.get("amount")
            try:
                amount = int(amount)
                if amount > 0:
                    cur.execute("SELECT credits_bought FROM users WHERE id = %s", (user_id,))
                    row = cur.fetchone()
                    new_bought = max(0, (row["credits_bought"] or 0) - amount)
                    cur.execute("UPDATE users SET credits_bought = %s WHERE id = %s", (new_bought, user_id))
                    cur.execute(
                        "INSERT INTO credit_transactions (user_id, amount, credits_bought_after, credits_free_after, type, description) SELECT %s, %s, %s, credits_free_today, 'admin_sub', 'Списано из веб-админки' FROM users WHERE id = %s",
                        (user_id, -amount, new_bought, user_id),
                    )
                    conn.commit()
                    log_action("credits_sub", entity_id=user_id, details={"amount": amount}, ip=admin_ip())
                    flash(f"Списано {amount} CR")
            except (ValueError, TypeError):
                flash("Неверное количество", "error")
        elif action == "set_unlimited":
            days = request.form.get("days")
            try:
                days = int(days or 0)
                if days > 0:
                    cur.execute("UPDATE users SET unlimited_ends_at = NOW() + (%s || ' days')::INTERVAL WHERE id = %s", (days, user_id))
                    conn.commit()
                    log_action("unlimited_set", entity_id=user_id, details={"days": days}, ip=admin_ip())
                    flash(f"Безлимит на {days} дн.")
            except (ValueError, TypeError):
                flash("Укажите число дней", "error")
        elif action == "remove_unlimited":
            cur.execute("UPDATE users SET unlimited_ends_at = NULL WHERE id = %s", (user_id,))
            conn.commit()
            log_action("unlimited_remove", entity_id=user_id, ip=admin_ip())
            flash("Безлимит отключён")
        elif action == "note":
            note = (request.form.get("note") or "").strip()[:1000]
            if note:
                admin_id = int(os.environ.get("ADMIN_PANEL_NOTE_AS_USER_ID", "0"))
                try:
                    cur.execute("INSERT INTO user_notes (user_id, admin_id, note) VALUES (%s, %s, %s)", (user_id, admin_id, note))
                    conn.commit()
                    log_action("note_add", entity_id=user_id, details={"len": len(note)}, ip=admin_ip())
                    flash("Заметка добавлена")
                except Exception:
                    flash("Не удалось сохранить заметку", "error")
    finally:
        conn.close()
    return redirect(request.referrer or url_for("user_detail", user_id=user_id))
