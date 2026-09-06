"""
Flask Blueprint for the data_feed_history viewer/editor.

Routes:
  GET   /view                     — history HTML page
  GET   /api/history/periods      — distinct time_period values with row counts
  GET   /api/history              — paginated rows (?period=<p>&page=<n>)
  POST  /api/history              — create a manual entry (exclude_from_training=True)
  PATCH /api/history/<id>         — update editable fields for one row
  DELETE /api/history/<id>        — delete a row
  GET   /api/settings             — return all app settings
  PATCH /api/settings             — update one or more settings

Auth: if ADMIN_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

from datetime import date as _date

from flask import Blueprint, abort, jsonify, request

import db
from token_auth import require_admin as _require_token

history_bp = Blueprint("history", __name__)

_SHARED_SCOPE_START = db._SHARED_SCOPE_START




@history_bp.route("/api/history/periods")
@_require_token
def list_periods():
    conn = db.get_connection()
    try:
        periods = db.get_history_periods(conn)
        return jsonify(periods)
    finally:
        conn.close()


@history_bp.route("/api/history")
@_require_token
def list_history():
    period = request.args.get("period", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = min(5000, max(1, int(request.args.get("page_size", 25))))
    except (ValueError, TypeError):
        page_size = 25
    if not period:
        return jsonify({"items": [], "total": 0, "page": 1, "pages": 1})
    conn = db.get_connection()
    try:
        result = db.get_history_page(conn, period, page, page_size=page_size)
        return jsonify(result)
    finally:
        conn.close()


@history_bp.route("/api/history/summary")
@_require_token
def history_summary():
    period = request.args.get("period", "").strip()
    if not period:
        return jsonify({"top_categories": []})
    prev_period = request.args.get("prev_period", "").strip() or None
    conn = db.get_connection()
    try:
        result = db.get_history_summary(conn, period, prev_period)
        return jsonify(result)
    finally:
        conn.close()


@history_bp.route("/api/history", methods=["POST"])
@_require_token
def create_history():
    data = request.get_json(force=True)
    entry_date_str = (data.get("entry_date") or "").strip()
    entry_text = (data.get("entry_text") or "").strip()
    amount_raw = data.get("amount")
    if not entry_date_str or not entry_text or amount_raw is None:
        abort(400, "entry_date, entry_text, and amount are required")
    try:
        entry_date = _date.fromisoformat(entry_date_str)
    except ValueError:
        abort(400, "entry_date must be YYYY-MM-DD")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")

    merchant = (data.get("merchant") or "").strip() or None
    category = (data.get("category") or "").strip() or None
    sub_category = (data.get("sub_category") or "").strip() or None
    spend_type = (data.get("spend_type") or "").strip() or None
    cadence = (data.get("cadence") or "O").strip()
    divide_by = max(1, int(data.get("divide_by") or 1))
    shared_expense = (data.get("shared_expense") or "N").strip().upper()[:1]
    share_ratio = float(data.get("share_ratio") or 1.0)
    monthly_amount = round(amount / divide_by, 2)
    final_amount = round(monthly_amount * share_ratio, 2)
    time_period = entry_date.strftime("%b-%Y")

    conn = db.get_connection()
    try:
        db.create_data_feed_table(conn)
        if cadence == 'A' and divide_by > 1:
            ids = []
            for i in range(divide_by):
                if i == 0:
                    period_date = entry_date
                else:
                    m = entry_date.month - 1 + i
                    period_date = _date(entry_date.year + m // 12, m % 12 + 1, 1)
                tp = period_date.strftime("%b-%Y")
                row_id = db.insert_data_feed_row(
                    conn, period_date, entry_text, sub_category, category, spend_type,
                    amount, merchant, None, None,
                    time_period=tp,
                    cadence=cadence,
                    divide_by=divide_by,
                    monthly_amount=monthly_amount,
                    shared_expense=shared_expense,
                    share_ratio=share_ratio,
                    final_amount=final_amount,
                    exclude_from_training=True,
                )
                ids.append(row_id)
                if shared_expense == 'Y' and period_date >= _SHARED_SCOPE_START:
                    db.upsert_shared_transaction(
                        conn, row_id, amount, monthly_amount, share_ratio,
                        period_date, merchant, category, sub_category, entry_text,
                    )
            return jsonify({"ok": True, "ids": ids, "count": len(ids)}), 201
        else:
            row_id = db.insert_data_feed_row(
                conn, entry_date, entry_text, sub_category, category, spend_type,
                amount, merchant, None, None,
                time_period=time_period,
                cadence=cadence,
                divide_by=divide_by,
                monthly_amount=monthly_amount,
                shared_expense=shared_expense,
                share_ratio=share_ratio,
                final_amount=final_amount,
                exclude_from_training=True,
            )
            if shared_expense == 'Y' and entry_date >= _SHARED_SCOPE_START:
                db.upsert_shared_transaction(
                    conn, row_id, amount, monthly_amount, share_ratio,
                    entry_date, merchant, category, sub_category, entry_text,
                )
            return jsonify({"ok": True, "id": row_id, "count": 1}), 201
    finally:
        conn.close()


@history_bp.route("/api/history/<int:row_id>", methods=["DELETE"])
@_require_token
def delete_history(row_id):
    conn = db.get_connection()
    try:
        found = db.delete_history_row(conn, row_id)
        if not found:
            abort(404, "Row not found")
        return ("", 204)
    finally:
        conn.close()


@history_bp.route("/api/history/<int:row_id>", methods=["PATCH"])
@_require_token
def update_history(row_id):
    data = request.get_json(force=True)
    fields = {}
    if "amount" in data:
        raw_amount = data.get("amount")
        fields["amount"] = float(raw_amount) if raw_amount is not None else None
    if "time_period" in data:
        fields["time_period"] = (data.get("time_period") or "").strip() or None
    if "category" in data:
        fields["category"] = (data.get("category") or "").strip()
    if "sub_category" in data:
        fields["sub_category"] = (data.get("sub_category") or "").strip()
    if "spend_type" in data:
        fields["spend_type"] = (data.get("spend_type") or "").strip()
    if "cadence" in data:
        fields["cadence"] = (data.get("cadence") or "O").strip()
    if "divide_by" in data:
        fields["divide_by"] = max(1, int(data.get("divide_by") or 1))
    if "shared_expense" in data:
        fields["shared_expense"] = (data.get("shared_expense") or "N").strip().upper()[:1]
    if "share_ratio" in data:
        fields["share_ratio"] = float(data.get("share_ratio") or 1.0)

    conn = db.get_connection()
    try:
        result = db.update_history_row(conn, row_id, fields)
        if result is None:
            abort(404, "Row not found")

        rows_created = 0
        expansion_relevant_fields = {"amount", "cadence", "divide_by"}
        if (expansion_relevant_fields & fields.keys()
                and result["cadence"] == "A" and result["divide_by"] > 1):
            existing = db.get_history_row(conn, row_id)
            if existing and existing.get("entry_date"):
                base_date = existing["entry_date"]
                divide_by = result["divide_by"]
                share_ratio = result["share_ratio"]
                shared_expense = result["shared_expense"]
                monthly_amount = result["monthly_amount"]
                final_amount = result["final_amount"]
                entry_text = existing["entry_text"]
                merchant = existing["merchant"]
                sub_category = result["sub_category"] or None
                category = result["category"] or None
                spend_type = result["spend_type"] or None

                # Build all 11 possible future time_periods (covers divide_by up to 12)
                future_periods = []
                for i in range(1, 12):
                    m = base_date.month - 1 + i
                    fp = _date(base_date.year + m // 12, m % 12 + 1, 1)
                    future_periods.append(fp.strftime("%b-%Y"))

                # Delete any pre-existing future rows for this *same* recurring item
                # (entry_text alone is not unique - e.g. "Online Learning" is shared by
                # several distinct subscriptions, so match on merchant/category/sub_category
                # too to avoid deleting sibling items that happen to share the label)
                with conn.cursor() as cur:
                    placeholders = ",".join(["%s"] * len(future_periods))
                    cur.execute(
                        f"""
                        DELETE FROM data_feed_history
                        WHERE entry_text = %s AND id != %s AND time_period IN ({placeholders})
                          AND merchant IS NOT DISTINCT FROM %s
                          AND category IS NOT DISTINCT FROM %s
                          AND sub_category IS NOT DISTINCT FROM %s
                        """,
                        [entry_text, row_id] + future_periods + [merchant, category, sub_category],
                    )
                conn.commit()

                # Create new rows for months 2..divide_by
                for i in range(1, divide_by):
                    m = base_date.month - 1 + i
                    period_date = _date(base_date.year + m // 12, m % 12 + 1, 1)
                    new_id = db.insert_data_feed_row(
                        conn,
                        period_date, entry_text, sub_category, category, spend_type,
                        monthly_amount,
                        merchant=merchant,
                        time_period=period_date.strftime("%b-%Y"),
                        cadence="A",
                        divide_by=divide_by,
                        monthly_amount=monthly_amount,
                        shared_expense=shared_expense,
                        share_ratio=share_ratio,
                        final_amount=final_amount,
                        exclude_from_training=True,
                    )
                    rows_created += 1
                    if shared_expense == 'Y' and period_date >= _SHARED_SCOPE_START:
                        db.upsert_shared_transaction(
                            conn, new_id, monthly_amount, monthly_amount, share_ratio,
                            period_date, None, category, sub_category, entry_text,
                        )

        # Sync the updated row itself to shared_transactions
        new_shared = result["shared_expense"]
        if new_shared == 'Y':
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT entry_date, merchant, entry_text FROM data_feed_history WHERE id = %s",
                    (row_id,),
                )
                dfh = cur.fetchone()
            if dfh and dfh[0] and dfh[0] >= _SHARED_SCOPE_START:
                db.upsert_shared_transaction(
                    conn, row_id, result["amount"], result["monthly_amount"], result["share_ratio"],
                    dfh[0], dfh[1], result["category"] or None,
                    result["sub_category"] or None, dfh[2],
                )
        else:
            db.delete_shared_transaction(conn, row_id)

        return jsonify({"ok": True, **result, "rows_created": rows_created})
    finally:
        conn.close()


@history_bp.route("/api/settings")
@_require_token
def get_settings():
    conn = db.get_connection()
    try:
        settings = db.get_settings(conn)
        return jsonify(settings)
    finally:
        conn.close()


@history_bp.route("/api/settings", methods=["PATCH"])
@_require_token
def update_settings():
    data = request.get_json(force=True)
    allowed = {"default_share_ratio", "default_annual_divisor"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        abort(400, f"No valid settings keys provided. Allowed: {sorted(allowed)}")

    errors = {}
    if "default_share_ratio" in updates:
        try:
            v = float(updates["default_share_ratio"])
            if not (0 < v <= 1):
                errors["default_share_ratio"] = "must be between 0 and 1"
            else:
                updates["default_share_ratio"] = v
        except (TypeError, ValueError):
            errors["default_share_ratio"] = "must be a number"
    if "default_annual_divisor" in updates:
        try:
            v = int(updates["default_annual_divisor"])
            if v < 1:
                errors["default_annual_divisor"] = "must be >= 1"
            else:
                updates["default_annual_divisor"] = v
        except (TypeError, ValueError):
            errors["default_annual_divisor"] = "must be an integer"
    if errors:
        abort(400, str(errors))

    conn = db.get_connection()
    try:
        for key, value in updates.items():
            db.update_setting(conn, key, str(value))
        settings = db.get_settings(conn)
        return jsonify({"ok": True, **settings})
    finally:
        conn.close()
