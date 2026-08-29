"""
Flask Blueprint for managing recurring transaction definitions.

Routes:
  GET   /recurring                  — recurring transactions HTML page
  GET   /api/recurring              — list all definitions
  POST  /api/recurring              — create a new definition
  PUT   /api/recurring/<id>         — full update of a definition
  DELETE /api/recurring/<id>        — delete a definition
  POST  /api/recurring/generate     — manually trigger generation for current month

Auth: if ADMIN_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

from datetime import date as _date

from flask import Blueprint, abort, jsonify, request

import db
from token_auth import require_admin as _require_token

recurring_bp = Blueprint("recurring", __name__)


@recurring_bp.route("/api/recurring")
@_require_token
def list_recurring():
    conn = db.get_connection()
    try:
        items = db.get_recurring_transactions(conn)
        return jsonify(items)
    finally:
        conn.close()


@recurring_bp.route("/api/recurring", methods=["POST"])
@_require_token
def create_recurring():
    data = request.get_json(force=True)
    entry_text = (data.get("entry_text") or "").strip()
    amount_raw = data.get("amount")
    if not entry_text:
        abort(400, "entry_text is required")
    if amount_raw is None:
        abort(400, "amount is required")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")

    payload = {
        "entry_text":     entry_text,
        "merchant":       (data.get("merchant") or "").strip() or None,
        "amount":         amount,
        "category":       (data.get("category") or "").strip() or None,
        "sub_category":   (data.get("sub_category") or "").strip() or None,
        "spend_type":     (data.get("spend_type") or "").strip() or None,
        "cadence":        (data.get("cadence") or "O").strip(),
        "divide_by":      max(1, int(data.get("divide_by") or 1)),
        "shared_expense": (data.get("shared_expense") or "N").strip().upper()[:1],
        "share_ratio":    float(data.get("share_ratio") or 1.0),
        "active":         bool(data.get("active", True)),
    }
    conn = db.get_connection()
    try:
        db.create_recurring_table(conn)
        new_id = db.upsert_recurring_transaction(conn, payload)
        return jsonify({"ok": True, "id": new_id}), 201
    finally:
        conn.close()


@recurring_bp.route("/api/recurring/<int:row_id>", methods=["PUT"])
@_require_token
def update_recurring(row_id):
    data = request.get_json(force=True)
    entry_text = (data.get("entry_text") or "").strip()
    amount_raw = data.get("amount")
    if not entry_text:
        abort(400, "entry_text is required")
    if amount_raw is None:
        abort(400, "amount is required")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")

    payload = {
        "entry_text":     entry_text,
        "merchant":       (data.get("merchant") or "").strip() or None,
        "amount":         amount,
        "category":       (data.get("category") or "").strip() or None,
        "sub_category":   (data.get("sub_category") or "").strip() or None,
        "spend_type":     (data.get("spend_type") or "").strip() or None,
        "cadence":        (data.get("cadence") or "O").strip(),
        "divide_by":      max(1, int(data.get("divide_by") or 1)),
        "shared_expense": (data.get("shared_expense") or "N").strip().upper()[:1],
        "share_ratio":    float(data.get("share_ratio") or 1.0),
        "active":         bool(data.get("active", True)),
    }
    conn = db.get_connection()
    try:
        updated_id = db.upsert_recurring_transaction(conn, payload, row_id=row_id)
        if updated_id is None:
            abort(404, "Definition not found")
        return jsonify({"ok": True})
    finally:
        conn.close()


@recurring_bp.route("/api/recurring/<int:row_id>", methods=["DELETE"])
@_require_token
def delete_recurring(row_id):
    conn = db.get_connection()
    try:
        deleted = db.delete_recurring_transaction(conn, row_id)
        if not deleted:
            abort(404, "Definition not found")
        return ("", 204)
    finally:
        conn.close()


@recurring_bp.route("/api/recurring/generate", methods=["POST"])
@_require_token
def generate_recurring():
    date_param = request.args.get("date", "").strip()
    today = None
    if date_param:
        try:
            today = _date.fromisoformat(date_param)
        except ValueError:
            abort(400, "date must be YYYY-MM-DD")

    conn = db.get_connection()
    try:
        db.create_recurring_table(conn)
        generated = db.generate_recurring_entries(conn, today=today)
        return jsonify({"ok": True, "generated": generated, "count": len(generated)})
    finally:
        conn.close()
