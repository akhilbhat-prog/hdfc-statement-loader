"""
Flask Blueprint for the batch review UI.

Routes:
  GET    /api/batches                         — list pending/reviewed batches
  GET    /api/batches/<id>                    — batch details + items
  PATCH  /api/batches/<id>/items/<txn_id>     — save edits (category/subcategory/type)
  DELETE /api/batches/<id>/items/<txn_id>     — remove item; permanently excludes transaction
  DELETE /api/batches/<id>                    — delete entire pending/reviewed batch
  POST   /api/batches/<id>/mark-reviewed      — set batch status = 'reviewed'
  POST   /api/batches/<id>/complete           — complete batch, trigger retraining
  GET    /api/categories                      — {categories, types} merged from rules.json + data_feed_history

Auth: if ADMIN_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import date as _date

from flask import Blueprint, abort, jsonify, request

import db
from token_auth import require_admin as _require_token

logger = logging.getLogger(__name__)

review_bp = Blueprint("review", __name__)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RULES_PATH = os.path.join(_project_root, "categorizer", "config", "rules.json")
_SHARED_SCOPE_START = db._SHARED_SCOPE_START


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches")
@_require_token
def list_batches():
    include_complete = request.args.get("include_complete") == "1"
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            if include_complete:
                cur.execute("""
                    SELECT id, row_count, status, created_at
                    FROM transaction_batches
                    ORDER BY created_at DESC
                """)
            else:
                cur.execute("""
                    SELECT id, row_count, status, created_at
                    FROM transaction_batches
                    WHERE status != 'complete'
                    ORDER BY created_at DESC
                """)
            rows = cur.fetchall()
        return jsonify([
            {
                "id": r[0],
                "row_count": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ])
    finally:
        conn.close()


@review_bp.route("/api/batches/<int:batch_id>")
@_require_token
def get_batch(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, row_count, status, created_at FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            b = cur.fetchone()
            if not b:
                abort(404, "Batch not found")
            batch = {
                "id": b[0],
                "row_count": b[1],
                "status": b[2],
                "created_at": b[3].isoformat() if b[3] else None,
            }

            cur.execute("""
                SELECT tbi.transaction_id,
                       tbi.pred_category, tbi.pred_subcategory, tbi.pred_type,
                       tbi.pred_confidence, tbi.pred_source,
                       tbi.category, tbi.subcategory, tbi.type,
                       t.date, t.raw_entry, COALESCE(tbi.amount, t.amount) AS amount,
                       t.merchant, t.vpa,
                       tbi.cadence, tbi.divide_by, tbi.shared_expense, tbi.share_ratio
                FROM transaction_batch_items tbi
                JOIN transactions t ON t.id = tbi.transaction_id
                WHERE tbi.batch_id = %s
                ORDER BY t.date, t.id
            """, (batch_id,))
            rows = cur.fetchall()

        items = [
            {
                "transaction_id": r[0],
                "pred_category":    r[1],
                "pred_subcategory": r[2],
                "pred_type":        r[3],
                "pred_confidence":  float(r[4]) if r[4] is not None else None,
                "pred_source":      r[5],
                "category":         r[6],
                "subcategory":      r[7],
                "type":             r[8],
                "date":             r[9].isoformat() if r[9] else None,
                "raw_entry":        r[10],
                "amount":           float(r[11]) if r[11] is not None else None,
                "merchant":         r[12],
                "vpa":              r[13],
                "cadence":          r[14] if r[14] is not None else "O",
                "divide_by":        r[15] if r[15] is not None else 1,
                "shared_expense":   r[16] if r[16] is not None else "N",
                "share_ratio":      float(r[17]) if r[17] is not None else 1.0,
            }
            for r in rows
        ]
        return jsonify({"batch": batch, "items": items})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Item edits
# ---------------------------------------------------------------------------

_ITEM_FIELD_COERCERS = {
    "category":       lambda v: (v or "").strip(),
    "subcategory":    lambda v: (v or "").strip(),
    "type":           lambda v: (v or "").strip(),
    "cadence":        lambda v: (v or "O").strip(),
    "divide_by":      lambda v: int(v or 1),
    "shared_expense": lambda v: (v or "N").strip().upper()[:1],
    "share_ratio":    lambda v: float(v or 1.0),
    "amount":         lambda v: float(v) if v is not None else None,
}


@review_bp.route("/api/batches/<int:batch_id>/items/<int:txn_id>", methods=["PATCH"])
@_require_token
def update_item(batch_id, txn_id):
    data = request.get_json(force=True)

    columns = []
    params = []
    for field, coerce in _ITEM_FIELD_COERCERS.items():
        if field in data:
            columns.append(field)
            params.append(coerce(data[field]))

    if not columns:
        abort(400, "No recognized fields to update")

    set_clause = ", ".join(f"{col} = %s" for col in columns)
    params.extend([batch_id, txn_id])

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE transaction_batch_items
                SET {set_clause}
                WHERE batch_id = %s AND transaction_id = %s
                """,
                params,
            )
            if cur.rowcount == 0:
                abort(404, "Item not found")
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Item delete
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches/<int:batch_id>/items/<int:txn_id>", methods=["DELETE"])
@_require_token
def delete_item(batch_id, txn_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM transaction_batch_items WHERE batch_id = %s AND transaction_id = %s",
                (batch_id, txn_id),
            )
            if cur.rowcount == 0:
                abort(404, "Item not found")
            cur.execute(
                "INSERT INTO transaction_exclusions (transaction_id, reason) "
                "VALUES (%s, 'user_deleted') ON CONFLICT (transaction_id) DO NOTHING",
                (txn_id,),
            )
            cur.execute(
                "UPDATE transaction_batches SET row_count = GREATEST(row_count - 1, 0) WHERE id = %s",
                (batch_id,),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Batch delete
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches/<int:batch_id>", methods=["DELETE"])
@_require_token
def delete_batch(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
            if not row:
                abort(404, "Batch not found")
            if row[0] == "complete":
                abort(400, "Cannot delete a completed batch")
            cur.execute(
                "DELETE FROM transaction_batch_items WHERE batch_id = %s",
                (batch_id,),
            )
            cur.execute(
                "DELETE FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches/<int:batch_id>/mark-reviewed", methods=["POST"])
@_require_token
def mark_reviewed(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
            if not row:
                abort(404, "Batch not found")
            if row[0] == "reviewed":
                return jsonify({"ok": True, "status": "reviewed"})
            if row[0] != "pending":
                abort(400, f"Batch is '{row[0]}', cannot mark as reviewed")
            cur.execute(
                "UPDATE transaction_batches SET status = 'reviewed' WHERE id = %s",
                (batch_id,),
            )
        conn.commit()
        return jsonify({"ok": True, "status": "reviewed"})
    finally:
        conn.close()


@review_bp.route("/api/batches/<int:batch_id>/complete", methods=["POST"])
@_require_token
def complete_batch(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
            if not row:
                abort(404, "Batch not found")
            if row[0] != "reviewed":
                abort(400, f"Batch must be 'reviewed' before completing (current: '{row[0]}')")

        db.create_data_feed_table(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.date, t.raw_entry, COALESCE(tbi.amount, t.amount) AS amount,
                       COALESCE(NULLIF(TRIM(tbi.category),    ''), tbi.pred_category)    AS category,
                       COALESCE(NULLIF(TRIM(tbi.subcategory), ''), tbi.pred_subcategory) AS subcategory,
                       COALESCE(NULLIF(TRIM(tbi.type),        ''), tbi.pred_type)        AS txn_type,
                       t.merchant, t.vpa, t.upi_ref,
                       tbi.cadence, tbi.divide_by, tbi.shared_expense, tbi.share_ratio
                FROM transaction_batch_items tbi
                JOIN transactions t ON t.id = tbi.transaction_id
                WHERE tbi.batch_id = %s
                """,
                (batch_id,),
            )
            items = cur.fetchall()

        inserted = 0
        for (date, entry, amount, category, subcategory, txn_type,
             merchant, vpa, upi_ref, cadence, divide_by, shared_expense, share_ratio) in items:
            divide_by = divide_by or 1
            share_ratio = float(share_ratio) if share_ratio is not None else 1.0
            amount_val = float(amount) if amount is not None else 0.0
            monthly_amount = round(amount_val / divide_by, 2)
            final_amount = round(monthly_amount * share_ratio, 2)
            time_period = date.strftime("%b-%Y") if date else None
            feed_id = db.insert_data_feed_row(
                conn, date, entry, subcategory, category, txn_type, amount,
                merchant, vpa, upi_ref,
                time_period=time_period,
                cadence=cadence or "O",
                divide_by=divide_by,
                monthly_amount=monthly_amount,
                shared_expense=shared_expense or "N",
                share_ratio=share_ratio,
                final_amount=final_amount,
            )
            if feed_id:
                inserted += 1
                row_date = date.date() if date else None
                if (shared_expense or "N") == "Y" and row_date and row_date >= _SHARED_SCOPE_START:
                    db.upsert_shared_transaction(
                        conn, feed_id, amount_val, monthly_amount, share_ratio,
                        row_date, merchant, category, subcategory, entry or "",
                    )

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE transaction_batches SET status = 'complete', completed_at = NOW() WHERE id = %s",
                (batch_id,),
            )
        conn.commit()

        _trigger_retraining()
        return jsonify({"ok": True, "inserted": inserted})
    finally:
        conn.close()


_retraining_proc: subprocess.Popen | None = None


def is_retraining() -> bool:
    """Return True if a model retraining subprocess is currently running."""
    global _retraining_proc
    if _retraining_proc is not None and _retraining_proc.poll() is None:
        return True
    _retraining_proc = None
    return False


def _trigger_retraining():
    global _retraining_proc
    main_py = os.path.join(_project_root, "categorizer", "main.py")
    if not os.path.exists(main_py):
        return
    if is_retraining():
        logger.info("Model retraining already in progress — skipping duplicate trigger.")
        return
    try:
        _retraining_proc = subprocess.Popen(
            [sys.executable, main_py],
            cwd=os.path.join(_project_root, "categorizer"),
        )
        logger.info("Model retraining triggered in background.")
    except Exception:
        logger.exception("Failed to trigger model retraining.")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@review_bp.route("/api/categories")
@_require_token
def get_categories():
    """Return { categories: {cat: [subcats]}, types: [...] } merged from rules.json + data_feed_history."""
    cat_map: dict[str, set] = {}
    type_set: set[str] = set()

    # Seed from rules.json
    try:
        with open(_RULES_PATH, encoding="utf-8") as f:
            rules = json.load(f)
        for rule in rules.values():
            cat = rule.get("category", "")
            sub = rule.get("subcategory", "")
            if cat:
                cat_map.setdefault(cat, set()).add(sub)
    except Exception:
        pass

    # Enrich from data_feed_history (the ground truth).
    # Try new column names first; fall back to old schema (expense/type) if the
    # table was created before the column rename migration.
    try:
        conn = db.get_connection()
        try:
            rows = None
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT category, sub_category, spend_type
                        FROM data_feed_history
                        WHERE category IS NOT NULL AND category <> ''
                    """)
                    rows = cur.fetchall()
            except Exception as e:
                conn.rollback()
                logger.warning("data_feed_history new-schema query failed (%s); trying old schema", e)
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT DISTINCT category, expense, type
                            FROM data_feed_history
                            WHERE category IS NOT NULL AND category <> ''
                        """)
                        rows = cur.fetchall()
                except Exception as e2:
                    logger.error("data_feed_history old-schema query also failed: %s", e2)

            if rows:
                for cat, sub, spend_type in rows:
                    cat_map.setdefault(cat, set()).add(sub or "")
                    if spend_type:
                        type_set.add(spend_type)
            else:
                logger.info("data_feed_history returned no rows; categories will be rules.json only")
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Could not connect to DB for category enrichment: %s", e)

    categories = {cat: sorted(s for s in subs if s) for cat, subs in sorted(cat_map.items())}
    types = sorted(type_set) or ["expense", "income", "investment", "transfer"]
    return jsonify({"categories": categories, "types": types})
