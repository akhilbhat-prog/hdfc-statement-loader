"""
Flask Blueprint for the shared transactions mirror table.

Routes:
  GET   /shared                     — shared transactions HTML page
  GET   /api/shared/fy-list         — available financial year start years
  GET   /api/shared?fy=<year>       — all shared rows for a financial year
  GET   /api/shared/summary?fy=<y>  — aggregate stats for summary cards
  PATCH /api/shared/<id>            — update paid_by, owed_by, or settled
  DELETE /api/shared/<id>           — remove row from mirror

Auth: ADMIN_TOKEN grants full access. Valid user session (role='user') also grants access.
"""

from datetime import date as _date

from flask import Blueprint, abort, jsonify, request

import db
from token_auth import require_any_auth as _require_token

shared_bp = Blueprint("shared", __name__)

_DEFAULT_FY_YEAR = 2026


def _current_fy_year() -> int:
    today = _date.today()
    return today.year if today.month >= 4 else today.year - 1


@shared_bp.route("/api/shared/fy-list")
@_require_token
def shared_fy_list():
    conn = db.get_connection()
    try:
        years = db.get_shared_fy_list(conn)
        if not years:
            years = [_current_fy_year()]
        return jsonify(years)
    finally:
        conn.close()


@shared_bp.route("/api/shared")
@_require_token
def list_shared():
    try:
        fy_year = int(request.args.get("fy", _current_fy_year()))
    except (ValueError, TypeError):
        fy_year = _current_fy_year()
    conn = db.get_connection()
    try:
        rows = db.get_shared_transactions(conn, fy_year)
        return jsonify(rows)
    finally:
        conn.close()


@shared_bp.route("/api/shared/summary")
@_require_token
def shared_summary():
    try:
        fy_year = int(request.args.get("fy", _current_fy_year()))
    except (ValueError, TypeError):
        fy_year = _current_fy_year()
    conn = db.get_connection()
    try:
        summary = db.get_shared_summary(conn, fy_year)
        return jsonify(summary)
    finally:
        conn.close()


@shared_bp.route("/api/shared/payment", methods=["POST"])
@_require_token
def record_payment():
    data = request.get_json(force=True)
    date_str = (data.get("entry_date") or "").strip()
    if not date_str:
        abort(400, "entry_date is required")
    try:
        entry_date = _date.fromisoformat(date_str)
    except ValueError:
        abort(400, "entry_date must be YYYY-MM-DD")
    paid_by = str(data.get("paid_by") or "").strip()
    if paid_by not in ("Akhil", "Aditi"):
        abort(400, "paid_by must be 'Akhil' or 'Aditi'")
    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")
    if amount <= 0:
        abort(400, "amount must be greater than 0")
    owed_by = str(data.get("owed_by") or ("Aditi" if paid_by == "Akhil" else "Akhil")).strip()
    if owed_by not in ("Akhil", "Aditi"):
        owed_by = "Aditi" if paid_by == "Akhil" else "Akhil"
    if paid_by == owed_by:
        abort(400, "paid_by and owed_by cannot be the same person")
    note = (data.get("note") or "").strip() or None
    conn = db.get_connection()
    try:
        row_id = db.insert_payment_shared_transaction(
            conn, entry_date, paid_by, owed_by, amount, note,
        )
        return jsonify({"ok": True, "id": row_id}), 201
    finally:
        conn.close()


@shared_bp.route("/api/shared", methods=["POST"])
@_require_token
def create_shared():
    entries = request.get_json(force=True)
    if not isinstance(entries, list):
        entries = [entries]
    if not entries:
        abort(400, "Request body must be a non-empty array")

    # Validate all rows before opening a DB connection
    parsed = []
    for i, entry in enumerate(entries):
        date_str = (entry.get("entry_date") or "").strip()
        if not date_str:
            abort(400, f"Row {i+1}: entry_date is required")
        try:
            entry_date = _date.fromisoformat(date_str)
        except ValueError:
            abort(400, f"Row {i+1}: entry_date must be YYYY-MM-DD")
        try:
            monthly_amount = float(entry.get("monthly_amount") or 0)
        except (TypeError, ValueError):
            abort(400, f"Row {i+1}: monthly_amount must be a number")
        if monthly_amount <= 0:
            abort(400, f"Row {i+1}: monthly_amount must be greater than 0")
        try:
            share_ratio = float(entry.get("share_ratio", 0.7))
        except (TypeError, ValueError):
            share_ratio = 0.7
        share_ratio = max(0.01, min(1.0, share_ratio))
        paid_by = str(entry.get("paid_by") or "Akhil").strip()
        owed_by = str(entry.get("owed_by") or "Aditi").strip()
        if paid_by not in ("Akhil", "Aditi"):
            paid_by = "Akhil"
        if owed_by not in ("Akhil", "Aditi"):
            owed_by = "Aditi"
        settled_raw = entry.get("settled", False)
        settled = settled_raw.lower() in ("true", "1", "yes") if isinstance(settled_raw, str) else bool(settled_raw)
        parsed.append({
            "entry_date":     entry_date,
            "merchant":       (entry.get("merchant")    or "").strip() or None,
            "category":       (entry.get("category")    or "").strip() or None,
            "subcategory":    (entry.get("subcategory") or "").strip() or None,
            "monthly_amount": monthly_amount,
            "share_ratio":    share_ratio,
            "paid_by":        paid_by,
            "owed_by":        owed_by,
            "settled":        settled,
        })

    conn = db.get_connection()
    try:
        ids = []
        for entry in parsed:
            row_id = db.insert_manual_shared_transaction(conn, **entry)
            ids.append(row_id)
        return jsonify({"ok": True, "ids": ids, "count": len(ids)}), 201
    finally:
        conn.close()


@shared_bp.route("/api/shared/<int:shared_id>", methods=["PATCH"])
@_require_token
def update_shared(shared_id):
    data = request.get_json(force=True)
    fields = {}
    if "paid_by" in data:
        v = str(data["paid_by"]).strip()
        if v not in ("Akhil", "Aditi"):
            abort(400, "paid_by must be 'Akhil' or 'Aditi'")
        fields["paid_by"] = v
    if "owed_by" in data:
        v = str(data["owed_by"]).strip()
        if v not in ("Akhil", "Aditi"):
            abort(400, "owed_by must be 'Akhil' or 'Aditi'")
        fields["owed_by"] = v
    if "settled" in data:
        fields["settled"] = data["settled"]
    if "is_ignored" in data:
        fields["is_ignored"] = data["is_ignored"]
    if "share_ratio" in data:
        try:
            v = float(data["share_ratio"])
            if not (0 < v <= 1):
                abort(400, "share_ratio must be between 0 and 1")
            fields["share_ratio"] = v
        except (TypeError, ValueError):
            abort(400, "share_ratio must be a number")
    if not fields:
        abort(400, "No valid fields provided")
    conn = db.get_connection()
    try:
        result = db.update_shared_row(conn, shared_id, fields)
        if result is None:
            abort(404, "Row not found")
        return jsonify({"ok": True, **result})
    finally:
        conn.close()


@shared_bp.route("/api/shared/<int:shared_id>", methods=["DELETE"])
@_require_token
def delete_shared(shared_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM shared_transactions WHERE id = %s", (shared_id,))
            deleted = cur.rowcount > 0
        conn.commit()
        if not deleted:
            abort(404, "Row not found")
        return ("", 204)
    finally:
        conn.close()
