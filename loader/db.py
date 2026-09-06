"""
PostgreSQL helpers for ExpTrack.

Tables managed here:
  transactions          — one row per parsed bank transaction
  processed_emails      — idempotency log; every Gmail message ID lands here
  data_feed_history     — finalised categorised transactions
  recurring_transactions — user-defined recurring entries auto-generated monthly
"""

import os
import logging
from datetime import datetime, timezone, date as _date
import calendar as _calendar

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

_SHARED_SCOPE_START = _date(2026, 4, 1)


def get_connection():
    """Return a new psycopg2 connection using the DATABASE_URL env var."""
    url = os.environ["DATABASE_URL"]
    return psycopg2.connect(url)


def create_tables(conn) -> None:
    """Create transactions and processed_emails tables if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id               SERIAL PRIMARY KEY,
                date             TIMESTAMPTZ,
                amount           NUMERIC(12, 2),
                type             VARCHAR(6),
                format           VARCHAR(20),
                account_last4    CHAR(4),
                card_last4       CHAR(4),
                vpa              TEXT,
                merchant         TEXT,
                raw_entry        TEXT,
                upi_ref          VARCHAR(30),
                gmail_message_id TEXT UNIQUE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE transactions ADD COLUMN IF NOT EXISTS raw_entry TEXT;

            CREATE TABLE IF NOT EXISTS processed_emails (
                gmail_message_id TEXT PRIMARY KEY,
                processed_at     TIMESTAMPTZ,
                status           VARCHAR(10),
                notes            TEXT
            );

            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS cadence VARCHAR(20) DEFAULT 'O';
            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS divide_by INTEGER DEFAULT 1;
            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS shared_expense CHAR(1) DEFAULT 'N';
            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(6,4) DEFAULT 1.0;

            CREATE TABLE IF NOT EXISTS transaction_exclusions (
                transaction_id INTEGER PRIMARY KEY REFERENCES transactions(id),
                excluded_at    TIMESTAMPTZ DEFAULT NOW(),
                reason         VARCHAR(50) DEFAULT 'user_deleted'
            );
        """)
    conn.commit()
    logger.debug("Tables verified / created.")


def is_already_processed(conn, gmail_message_id: str) -> bool:
    """Return True if this Gmail message ID has already been processed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_emails WHERE gmail_message_id = %s",
            (gmail_message_id,),
        )
        return cur.fetchone() is not None


def get_transaction_by_message_id(conn, gmail_message_id: str) -> dict | None:
    """Return {merchant, amount, type, date} for a message ID, or None if not found."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT merchant, amount, type, date FROM transactions WHERE gmail_message_id = %s",
            (gmail_message_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"merchant": row[0], "amount": row[1], "type": row[2], "date": row[3]}


def insert_transaction(conn, transaction_dict: dict, gmail_message_id: str) -> None:
    """
    Insert a parsed transaction.  Silently ignores duplicate gmail_message_id
    so the function is safe to call more than once for the same message.
    """
    params = {**transaction_dict, "gmail_message_id": gmail_message_id}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions
                (date, amount, type, format, account_last4, card_last4,
                 vpa, merchant, raw_entry, upi_ref, gmail_message_id)
            VALUES
                (%(date)s, %(amount)s, %(type)s, %(format)s, %(account_last4)s,
                 %(card_last4)s, %(vpa)s, %(merchant)s, %(raw_entry)s,
                 %(upi_ref)s, %(gmail_message_id)s)
            ON CONFLICT (gmail_message_id) DO NOTHING
            """,
            params,
        )
    conn.commit()
    logger.debug("Inserted transaction for message %s.", gmail_message_id)


def create_settings_table(conn) -> None:
    """Create app_settings table and seed default values if not present."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            INSERT INTO app_settings (key, value) VALUES ('default_share_ratio', '0.7')
                ON CONFLICT (key) DO NOTHING;
            INSERT INTO app_settings (key, value) VALUES ('default_annual_divisor', '12')
                ON CONFLICT (key) DO NOTHING;
        """)
    conn.commit()


def get_settings(conn) -> dict:
    """Return all app settings as a dict with typed values."""
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM app_settings")
        rows = cur.fetchall()
    result = {}
    for key, value in rows:
        if key == "default_share_ratio":
            result[key] = float(value)
        elif key == "default_annual_divisor":
            result[key] = int(value)
        else:
            result[key] = value
    return result


def update_setting(conn, key: str, value: str) -> None:
    """Upsert a single setting value."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (key, value),
        )
    conn.commit()


def create_data_feed_table(conn) -> None:
    """Create the data_feed_history table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS data_feed_history (
                id           SERIAL PRIMARY KEY,
                entry_date   DATE NOT NULL,
                entry_text   TEXT NOT NULL,
                sub_category TEXT,
                category     TEXT,
                spend_type   VARCHAR(20),
                amount       NUMERIC(12, 2) NOT NULL,
                merchant     TEXT,
                vpa          TEXT,
                upi_ref      TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS time_period VARCHAR(10);
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS cadence VARCHAR(20) DEFAULT 'O';
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS divide_by INTEGER DEFAULT 1;
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS monthly_amount NUMERIC(12,2);
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS shared_expense CHAR(1) DEFAULT 'N';
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(6,4) DEFAULT 1.0;
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS final_amount NUMERIC(12,2);
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS exclude_from_training BOOLEAN DEFAULT FALSE;
        """)
    conn.commit()


def insert_data_feed_row(
    conn,
    entry_date,
    entry_text: str,
    sub_category: str | None,
    category: str | None,
    spend_type: str | None,
    amount,
    merchant: str | None = None,
    vpa: str | None = None,
    upi_ref: str | None = None,
    time_period: str | None = None,
    cadence: str | None = "O",
    divide_by: int = 1,
    monthly_amount=None,
    shared_expense: str | None = "N",
    share_ratio=None,
    final_amount=None,
    exclude_from_training: bool = False,
) -> int:
    """Insert one row into data_feed_history. Returns the new row id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_feed_history
                (entry_date, entry_text, sub_category, category, spend_type,
                 amount, merchant, vpa, upi_ref,
                 time_period, cadence, divide_by, monthly_amount,
                 shared_expense, share_ratio, final_amount, exclude_from_training)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (entry_date, entry_text, sub_category, category, spend_type,
             amount, merchant, vpa, upi_ref,
             time_period, cadence, divide_by, monthly_amount,
             shared_expense, share_ratio, final_amount, exclude_from_training),
        )
        row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def get_history_periods(conn) -> list[dict]:
    """Return [{period, count}, ...] sorted newest-first by calendar month.

    Derives period from entry_date for rows where time_period is unset.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')) AS period,
                COUNT(*) AS cnt
            FROM data_feed_history
            WHERE entry_date IS NOT NULL
            GROUP BY COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY'))
            ORDER BY TO_DATE(
                COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')),
                'Mon-YYYY'
            ) DESC
        """)
        rows = cur.fetchall()
    return [{"period": r[0], "count": r[1]} for r in rows]


def get_history_page(conn, period: str, page: int, page_size: int = 25) -> dict:
    """Return {items, total, page, pages} for one time_period page."""
    offset = (page - 1) * page_size
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM data_feed_history
               WHERE COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')) = %s""",
            (period,),
        )
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT id, entry_date, time_period, merchant, entry_text, amount,
                   category, sub_category, spend_type,
                   cadence, divide_by, monthly_amount,
                   shared_expense, share_ratio, final_amount
            FROM data_feed_history
            WHERE COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')) = %s
            ORDER BY entry_date ASC, id ASC
            LIMIT %s OFFSET %s
        """, (period, page_size, offset))
        rows = cur.fetchall()
    items = [
        {
            "id":             r[0],
            "entry_date":     r[1].isoformat() if r[1] else None,
            "time_period":    r[2],
            "merchant":       r[3],
            "entry_text":     r[4],
            "amount":         float(r[5]) if r[5] is not None else None,
            "category":       r[6] or "",
            "sub_category":   r[7] or "",
            "spend_type":     r[8] or "",
            "cadence":        r[9] if r[9] is not None else "O",
            "divide_by":      r[10] if r[10] is not None else 1,
            "monthly_amount": float(r[11]) if r[11] is not None else None,
            "shared_expense": r[12] if r[12] is not None else "N",
            "share_ratio":    float(r[13]) if r[13] is not None else 1.0,
            "final_amount":   float(r[14]) if r[14] is not None else None,
        }
        for r in rows
    ]
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": items, "total": total, "page": page, "pages": pages}


def get_history_row(conn, row_id: int) -> dict | None:
    """Fetch entry_text, entry_date, time_period, and merchant for a single data_feed_history row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, entry_text, entry_date, time_period, merchant FROM data_feed_history WHERE id = %s",
            (row_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id":           row[0],
        "entry_text":   row[1],
        "entry_date":   row[2],
        "time_period":  row[3],
        "merchant":     row[4],
    }


def update_history_row(conn, row_id: int, fields: dict) -> dict | None:
    """Update editable fields of a data_feed_history row.

    `fields` may be a partial set — only keys explicitly present are changed;
    any field not included keeps its current DB value (it is never reset to a
    default). Returns the full merged row (including computed monthly/final
    amounts) or None if the row does not exist.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT amount, time_period, category, sub_category, spend_type,
                   cadence, divide_by, shared_expense, share_ratio
            FROM data_feed_history WHERE id = %s
            """,
            (row_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        current = {
            "amount":         float(row[0]) if row[0] is not None else 0.0,
            "time_period":    row[1],
            "category":       row[2],
            "sub_category":   row[3],
            "spend_type":     row[4],
            "cadence":        row[5] or "O",
            "divide_by":      row[6] or 1,
            "shared_expense": row[7] or "N",
            "share_ratio":    float(row[8]) if row[8] is not None else 1.0,
        }
        merged = {**current, **{k: v for k, v in fields.items() if k in current}}

        amount = float(merged["amount"]) if merged["amount"] is not None else 0.0
        divide_by = max(1, int(merged["divide_by"] or 1))
        share_ratio = float(merged["share_ratio"] or 1.0)
        monthly_amount = round(amount / divide_by, 2)
        final_amount = round(monthly_amount * share_ratio, 2)

        cur.execute("""
            UPDATE data_feed_history
               SET amount         = %s,
                   time_period    = %s,
                   category       = %s,
                   sub_category   = %s,
                   spend_type     = %s,
                   cadence        = %s,
                   divide_by      = %s,
                   shared_expense = %s,
                   share_ratio    = %s,
                   monthly_amount = %s,
                   final_amount   = %s
             WHERE id = %s
        """, (
            amount,
            merged["time_period"],
            merged["category"] or None,
            merged["sub_category"] or None,
            merged["spend_type"] or None,
            merged["cadence"] or "O",
            divide_by,
            merged["shared_expense"] or "N",
            share_ratio,
            monthly_amount,
            final_amount,
            row_id,
        ))
    conn.commit()
    return {
        "amount": amount,
        "time_period": merged["time_period"],
        "category": merged["category"],
        "sub_category": merged["sub_category"],
        "spend_type": merged["spend_type"],
        "cadence": merged["cadence"] or "O",
        "divide_by": divide_by,
        "shared_expense": merged["shared_expense"] or "N",
        "share_ratio": share_ratio,
        "monthly_amount": monthly_amount,
        "final_amount": final_amount,
    }


def delete_history_row(conn, row_id: int) -> bool:
    """Delete a data_feed_history row by id. Returns True if a row was deleted."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM data_feed_history WHERE id = %s", (row_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def get_history_summary(conn, period: str, prev_period: str | None = None) -> dict:
    """Return top-5 categories by spend for a time period, plus the period grand total.

    When prev_period is supplied each category also includes prev_total (the same
    category's spend in that period, or None if absent).
    """
    with conn.cursor() as cur:
        if prev_period:
            cur.execute(
                """
                SELECT
                    cat,
                    SUM(CASE WHEN period_key = %(cur)s  THEN amt END)  AS cur_total,
                    SUM(CASE WHEN period_key = %(prev)s THEN amt END)  AS prev_total,
                    COUNT(CASE WHEN period_key = %(cur)s THEN 1 END)   AS cnt,
                    SUM(SUM(CASE WHEN period_key = %(cur)s THEN amt END)) OVER () AS period_total
                FROM (
                    SELECT
                        COALESCE(NULLIF(TRIM(category), ''), 'Uncategorised') AS cat,
                        COALESCE(NULLIF(TRIM(time_period), ''),
                                 TO_CHAR(entry_date, 'Mon-YYYY'))             AS period_key,
                        COALESCE(final_amount, amount)                        AS amt
                    FROM data_feed_history
                    WHERE COALESCE(NULLIF(TRIM(time_period), ''),
                                   TO_CHAR(entry_date, 'Mon-YYYY')) IN (%(cur)s, %(prev)s)
                ) sub
                GROUP BY cat
                HAVING COUNT(CASE WHEN period_key = %(cur)s THEN 1 END) > 0
                ORDER BY cur_total DESC NULLS LAST
                LIMIT 5
                """,
                {"cur": period, "prev": prev_period},
            )
            rows = cur.fetchall()
            period_total = float(rows[0][4]) if rows and rows[0][4] is not None else 0.0
            return {
                "top_categories": [
                    {
                        "category":   r[0],
                        "total":      float(r[1]) if r[1] is not None else 0.0,
                        "prev_total": float(r[2]) if r[2] is not None else None,
                        "count":      r[3],
                    }
                    for r in rows
                ],
                "period_total": period_total,
            }
        else:
            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(category), ''), 'Uncategorised') AS category,
                    SUM(COALESCE(final_amount, amount))                   AS total,
                    COUNT(*)                                              AS cnt,
                    SUM(SUM(COALESCE(final_amount, amount))) OVER ()      AS period_total
                FROM data_feed_history
                WHERE COALESCE(NULLIF(TRIM(time_period), ''),
                               TO_CHAR(entry_date, 'Mon-YYYY')) = %s
                GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Uncategorised')
                ORDER BY SUM(COALESCE(final_amount, amount)) DESC
                LIMIT 5
                """,
                (period,),
            )
            rows = cur.fetchall()
            period_total = float(rows[0][3]) if rows and rows[0][3] is not None else 0.0
            return {
                "top_categories": [
                    {"category": r[0], "total": float(r[1]) if r[1] is not None else 0.0, "count": r[2]}
                    for r in rows
                ],
                "period_total": period_total,
            }


def create_shared_transactions_table(conn) -> None:
    """Create shared_transactions mirror table and backfill existing shared data_feed_history rows."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shared_transactions (
                id               SERIAL PRIMARY KEY,
                history_id       INT UNIQUE REFERENCES data_feed_history(id) ON DELETE CASCADE,
                paid_by          TEXT NOT NULL DEFAULT 'Akhil',
                owed_by          TEXT NOT NULL DEFAULT 'Aditi',
                amount           NUMERIC(12,2) NOT NULL,
                monthly_amount   NUMERIC(12,2),
                share_ratio      NUMERIC(6,4)  NOT NULL,
                akhil_share      NUMERIC(12,2) NOT NULL,
                aditi_share      NUMERIC(12,2) NOT NULL,
                balance          NUMERIC(12,2) NOT NULL,
                entry_date       DATE,
                merchant         TEXT,
                category         TEXT,
                subcategory      TEXT,
                entry_text       TEXT,
                settled          BOOLEAN NOT NULL DEFAULT FALSE,
                settled_at       TIMESTAMPTZ,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE IF EXISTS shared_transactions ADD COLUMN IF NOT EXISTS monthly_amount NUMERIC(12,2);
            ALTER TABLE IF EXISTS shared_transactions ADD COLUMN IF NOT EXISTS is_manual BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE IF EXISTS shared_transactions ADD COLUMN IF NOT EXISTS is_payment BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE IF EXISTS shared_transactions ADD COLUMN IF NOT EXISTS is_ignored BOOLEAN NOT NULL DEFAULT FALSE;
        """)
        cur.execute("""
            INSERT INTO shared_transactions
                (history_id, amount, monthly_amount, share_ratio, akhil_share, aditi_share, balance,
                 entry_date, merchant, category, subcategory, entry_text)
            SELECT
                id,
                amount,
                COALESCE(monthly_amount, amount),
                COALESCE(share_ratio, 1.0),
                ROUND(COALESCE(monthly_amount, amount) * COALESCE(share_ratio, 1.0), 2),
                ROUND(COALESCE(monthly_amount, amount) * (1.0 - COALESCE(share_ratio, 1.0)), 2),
                ROUND(COALESCE(monthly_amount, amount) * (1.0 - COALESCE(share_ratio, 1.0)), 2),
                entry_date,
                merchant,
                category,
                sub_category,
                entry_text
            FROM data_feed_history
            WHERE shared_expense = 'Y'
              AND entry_date >= %s
            ON CONFLICT (history_id) DO NOTHING
        """, (_SHARED_SCOPE_START,))
        # Patch existing rows that have monthly_amount = NULL (rows inserted before this column existed)
        cur.execute("""
            UPDATE shared_transactions st
               SET monthly_amount = COALESCE(dfh.monthly_amount, dfh.amount),
                   akhil_share    = ROUND(COALESCE(dfh.monthly_amount, dfh.amount) * st.share_ratio, 2),
                   aditi_share    = ROUND(COALESCE(dfh.monthly_amount, dfh.amount) * (1.0 - st.share_ratio), 2),
                   balance        = CASE WHEN st.paid_by = 'Akhil'
                                         THEN ROUND(COALESCE(dfh.monthly_amount, dfh.amount) * (1.0 - st.share_ratio), 2)
                                         ELSE ROUND(COALESCE(dfh.monthly_amount, dfh.amount) * st.share_ratio, 2) END
              FROM data_feed_history dfh
             WHERE st.history_id = dfh.id
               AND st.monthly_amount IS NULL
        """)
    conn.commit()


def upsert_shared_transaction(
    conn,
    history_id: int,
    amount: float,
    monthly_amount: float,
    share_ratio: float,
    entry_date,
    merchant: str | None,
    category: str | None,
    subcategory: str | None,
    entry_text: str | None,
) -> None:
    """Insert or update a shared_transactions row. Preserves paid_by/owed_by/settled on conflict."""
    ma = float(monthly_amount)
    akhil_share = round(ma * float(share_ratio), 2)
    aditi_share = round(ma * (1.0 - float(share_ratio)), 2)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shared_transactions
                (history_id, amount, monthly_amount, share_ratio, akhil_share, aditi_share, balance,
                 entry_date, merchant, category, subcategory, entry_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (history_id) DO UPDATE SET
                amount         = EXCLUDED.amount,
                monthly_amount = EXCLUDED.monthly_amount,
                share_ratio    = EXCLUDED.share_ratio,
                akhil_share    = EXCLUDED.akhil_share,
                aditi_share    = EXCLUDED.aditi_share,
                balance        = CASE WHEN shared_transactions.paid_by = 'Akhil'
                                      THEN EXCLUDED.aditi_share
                                      ELSE EXCLUDED.akhil_share END,
                entry_date     = EXCLUDED.entry_date,
                merchant       = EXCLUDED.merchant,
                category       = EXCLUDED.category,
                subcategory    = EXCLUDED.subcategory,
                entry_text     = EXCLUDED.entry_text
        """, (
            history_id, amount, monthly_amount, share_ratio, akhil_share, aditi_share, aditi_share,
            entry_date, merchant, category, subcategory, entry_text,
        ))
    conn.commit()


def delete_shared_transaction(conn, history_id: int) -> bool:
    """Delete a shared_transactions row by history_id. Returns True if a row was deleted."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shared_transactions WHERE history_id = %s", (history_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def insert_manual_shared_transaction(
    conn,
    entry_date,
    merchant: str | None,
    category: str | None,
    subcategory: str | None,
    monthly_amount: float,
    share_ratio: float,
    paid_by: str = "Akhil",
    owed_by: str = "Aditi",
    settled: bool = False,
) -> int:
    """Insert a manual entry directly into shared_transactions (history_id=NULL). Returns new id."""
    ma          = float(monthly_amount)
    sr          = float(share_ratio)
    akhil_share = round(ma * sr, 2)
    aditi_share = round(ma * (1.0 - sr), 2)
    balance     = aditi_share if paid_by == "Akhil" else akhil_share
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shared_transactions
                (amount, monthly_amount, share_ratio, akhil_share, aditi_share, balance,
                 paid_by, owed_by, settled, entry_date, merchant, category, subcategory,
                 is_manual)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
        """, (ma, ma, sr, akhil_share, aditi_share, balance,
              paid_by, owed_by, settled, entry_date, merchant, category, subcategory))
        row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def insert_payment_shared_transaction(
    conn,
    entry_date,
    paid_by: str,
    owed_by: str,
    amount: float,
    note: str | None,
) -> int:
    """Record a settlement payment in shared_transactions. Returns new id."""
    amt = float(amount)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shared_transactions
                (amount, monthly_amount, share_ratio, akhil_share, aditi_share, balance,
                 paid_by, owed_by, entry_date, merchant, entry_text,
                 is_manual, is_payment)
            VALUES (%s, %s, 1.0, 0, 0, %s, %s, %s, %s, 'Payment', %s, TRUE, TRUE)
            RETURNING id
        """, (amt, amt, amt, paid_by, owed_by, entry_date, note or 'Payment'))
        row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def get_shared_transactions(conn, fy_year: int) -> list[dict]:
    """Return all shared_transactions for FY Apr fy_year – Mar fy_year+1, newest first."""
    fy_start = _date(fy_year, 4, 1)
    fy_end   = _date(fy_year + 1, 4, 1)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, history_id, paid_by, owed_by, amount, monthly_amount, share_ratio,
                   akhil_share, aditi_share, balance,
                   entry_date, merchant, category, subcategory, entry_text,
                   settled, settled_at, is_payment, is_ignored
            FROM shared_transactions
            WHERE entry_date >= %s AND entry_date < %s
            ORDER BY entry_date DESC, id DESC
        """, (fy_start, fy_end))
        rows = cur.fetchall()
    return [
        {
            "id":             r[0],
            "history_id":     r[1],
            "paid_by":        r[2],
            "owed_by":        r[3],
            "amount":         float(r[4]) if r[4] is not None else 0.0,
            "monthly_amount": float(r[5]) if r[5] is not None else 0.0,
            "share_ratio":    float(r[6]) if r[6] is not None else 1.0,
            "akhil_share":    float(r[7]) if r[7] is not None else 0.0,
            "aditi_share":    float(r[8]) if r[8] is not None else 0.0,
            "balance":        float(r[9]) if r[9] is not None else 0.0,
            "entry_date":     r[10].isoformat() if r[10] else None,
            "merchant":       r[11],
            "category":       r[12] or "",
            "subcategory":    r[13] or "",
            "entry_text":     r[14] or "",
            "settled":        r[15],
            "settled_at":     r[16].isoformat() if r[16] else None,
            "is_payment":     bool(r[17]),
            "is_ignored":     bool(r[18]),
        }
        for r in rows
    ]


def update_shared_row(conn, shared_id: int, fields: dict) -> dict | None:
    """Update editable fields (paid_by, owed_by, share_ratio, settled, is_ignored) of a shared_transactions row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT paid_by, owed_by, share_ratio, monthly_amount, settled, is_ignored FROM shared_transactions WHERE id = %s",
            (shared_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        paid_by        = fields.get("paid_by",    row[0])
        owed_by        = fields.get("owed_by",    row[1])
        share_ratio    = float(fields.get("share_ratio", row[2]))
        monthly_amount = float(row[3]) if row[3] is not None else 0.0
        settled_new    = fields.get("settled")
        if settled_new is None:
            settled_new = row[4]
        elif isinstance(settled_new, str):
            settled_new = settled_new.lower() in ("true", "1", "yes")
        is_ignored_new = fields.get("is_ignored")
        if is_ignored_new is None:
            is_ignored_new = row[5]
        elif isinstance(is_ignored_new, str):
            is_ignored_new = is_ignored_new.lower() in ("true", "1", "yes")
        akhil_share = round(monthly_amount * share_ratio, 2)
        aditi_share = round(monthly_amount * (1.0 - share_ratio), 2)
        balance = aditi_share if paid_by == "Akhil" else akhil_share
        cur.execute("""
            UPDATE shared_transactions
               SET paid_by     = %s,
                   owed_by     = %s,
                   share_ratio = %s,
                   akhil_share = %s,
                   aditi_share = %s,
                   balance     = %s,
                   settled     = %s,
                   is_ignored  = %s,
                   settled_at  = CASE WHEN %s AND NOT settled THEN NOW()
                                      WHEN NOT %s THEN NULL
                                      ELSE settled_at END
             WHERE id = %s
        """, (paid_by, owed_by, share_ratio, akhil_share, aditi_share, balance,
              settled_new, is_ignored_new, settled_new, settled_new, shared_id))
        if cur.rowcount == 0:
            return None
    conn.commit()
    return {
        "paid_by": paid_by, "owed_by": owed_by, "share_ratio": share_ratio,
        "akhil_share": akhil_share, "aditi_share": aditi_share,
        "balance": balance, "settled": settled_new, "is_ignored": is_ignored_new,
    }


def get_shared_summary(conn, fy_year: int) -> dict:
    """Return aggregate stats for shared_transactions in a financial year."""
    fy_start = _date(fy_year, 4, 1)
    fy_end   = _date(fy_year + 1, 4, 1)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COALESCE(
                    SUM(CASE WHEN paid_by = 'Akhil' THEN balance ELSE 0 END)
                    - SUM(CASE WHEN paid_by = 'Aditi' THEN balance ELSE 0 END),
                    0
                ) AS net_balance,
                COALESCE(SUM(CASE WHEN NOT is_payment AND paid_by = 'Akhil' THEN monthly_amount ELSE 0 END), 0) AS akhil_paid,
                COALESCE(SUM(CASE WHEN NOT is_payment AND paid_by = 'Aditi' THEN monthly_amount ELSE 0 END), 0) AS aditi_paid
            FROM shared_transactions
            WHERE entry_date >= %s AND entry_date < %s
              AND NOT is_ignored
        """, (fy_start, fy_end))
        row = cur.fetchone()
    if not row:
        return {"net_balance": 0.0, "total_akhil_paid": 0.0, "total_aditi_paid": 0.0}
    return {
        "net_balance":      float(row[0] or 0),
        "total_akhil_paid": float(row[1] or 0),
        "total_aditi_paid": float(row[2] or 0),
    }


def get_shared_fy_list(conn) -> list[int]:
    """Return sorted list of FY start years (Apr–Mar) present in shared_transactions."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT
                CASE WHEN EXTRACT(MONTH FROM entry_date) >= 4
                     THEN EXTRACT(YEAR FROM entry_date)::INT
                     ELSE EXTRACT(YEAR FROM entry_date)::INT - 1
                END AS fy_year
            FROM shared_transactions
            WHERE entry_date IS NOT NULL
            ORDER BY fy_year DESC
        """)
        rows = cur.fetchall()
    return [r[0] for r in rows]


def find_duplicate_transaction(conn, transaction: dict) -> str | None:
    """
    Return the gmail_message_id of an existing transaction that matches the
    given parsed transaction, or None if no duplicate exists.

    UPI transactions match on upi_ref.
    All other formats match on (amount, date, format, merchant).
    """
    with conn.cursor() as cur:
        if transaction.get("upi_ref"):
            cur.execute(
                "SELECT gmail_message_id FROM transactions WHERE upi_ref = %s",
                (transaction["upi_ref"],),
            )
        else:
            cur.execute(
                """
                SELECT gmail_message_id FROM transactions
                WHERE amount = %s AND date = %s AND format = %s AND merchant = %s
                """,
                (transaction["amount"], transaction["date"],
                 transaction["format"], transaction["merchant"]),
            )
        row = cur.fetchone()
        return row[0] if row else None


def create_recurring_table(conn) -> None:
    """Create the recurring_transactions table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recurring_transactions (
                id              SERIAL PRIMARY KEY,
                entry_text      TEXT NOT NULL,
                merchant        TEXT,
                amount          NUMERIC(12, 2) NOT NULL,
                category        TEXT,
                sub_category    TEXT,
                spend_type      VARCHAR(20),
                cadence         VARCHAR(20) NOT NULL DEFAULT 'O',
                divide_by       INTEGER NOT NULL DEFAULT 1,
                shared_expense  CHAR(1) NOT NULL DEFAULT 'N',
                share_ratio     NUMERIC(6,4) NOT NULL DEFAULT 1.0,
                active          BOOLEAN NOT NULL DEFAULT TRUE,
                last_generated  DATE,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    conn.commit()


def get_recurring_transactions(conn) -> list[dict]:
    """Return all recurring transaction definitions, active first."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, entry_text, merchant, amount, category, sub_category,
                   spend_type, cadence, divide_by, shared_expense, share_ratio,
                   active, last_generated, created_at
            FROM recurring_transactions
            ORDER BY active DESC, id ASC
        """)
        rows = cur.fetchall()
    return [
        {
            "id":             r[0],
            "entry_text":     r[1],
            "merchant":       r[2],
            "amount":         float(r[3]) if r[3] is not None else None,
            "category":       r[4] or "",
            "sub_category":   r[5] or "",
            "spend_type":     r[6] or "",
            "cadence":        r[7] or "O",
            "divide_by":      r[8] if r[8] is not None else 1,
            "shared_expense": r[9] if r[9] is not None else "N",
            "share_ratio":    float(r[10]) if r[10] is not None else 1.0,
            "active":         r[11],
            "last_generated": r[12].isoformat() if r[12] else None,
            "created_at":     r[13].isoformat() if r[13] else None,
        }
        for r in rows
    ]


def upsert_recurring_transaction(conn, data: dict, row_id: int | None = None) -> int | None:
    """Insert (row_id=None) or update a recurring transaction definition. Returns id or None if not found."""
    if row_id is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recurring_transactions
                    (entry_text, merchant, amount, category, sub_category, spend_type,
                     cadence, divide_by, shared_expense, share_ratio, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    data["entry_text"],
                    data.get("merchant") or None,
                    data["amount"],
                    data.get("category") or None,
                    data.get("sub_category") or None,
                    data.get("spend_type") or None,
                    data.get("cadence") or "O",
                    data.get("divide_by") or 1,
                    data.get("shared_expense") or "N",
                    data.get("share_ratio") if data.get("share_ratio") is not None else 1.0,
                    data.get("active", True),
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE recurring_transactions
                   SET entry_text     = %s,
                       merchant       = %s,
                       amount         = %s,
                       category       = %s,
                       sub_category   = %s,
                       spend_type     = %s,
                       cadence        = %s,
                       divide_by      = %s,
                       shared_expense = %s,
                       share_ratio    = %s,
                       active         = %s
                 WHERE id = %s
                RETURNING id
                """,
                (
                    data["entry_text"],
                    data.get("merchant") or None,
                    data["amount"],
                    data.get("category") or None,
                    data.get("sub_category") or None,
                    data.get("spend_type") or None,
                    data.get("cadence") or "O",
                    data.get("divide_by") or 1,
                    data.get("shared_expense") or "N",
                    data.get("share_ratio") if data.get("share_ratio") is not None else 1.0,
                    data.get("active", True),
                    row_id,
                ),
            )
            row = cur.fetchone()
        if row is None:
            return None
        conn.commit()
        return row[0]


def delete_recurring_transaction(conn, row_id: int) -> bool:
    """Delete a recurring transaction definition. Returns True if deleted."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM recurring_transactions WHERE id = %s", (row_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def generate_recurring_entries(conn, today: _date | None = None) -> list[dict]:
    """Insert data_feed_history rows for all active recurring transactions not yet generated this month.

    entry_date is always the 1st of the current month.
    Returns a list of {id, feed_id, entry_text} for each generated row.
    """
    if today is None:
        today = _date.today()

    entry_date = _date(today.year, today.month, 1)
    time_period = entry_date.strftime("%b-%Y")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, entry_text, merchant, amount, category, sub_category,
                   spend_type, cadence, divide_by, shared_expense, share_ratio
            FROM recurring_transactions
            WHERE active = TRUE
              AND (last_generated IS NULL
                   OR DATE_TRUNC('month', last_generated) < DATE_TRUNC('month', %s::date))
            """,
            (today.isoformat(),),
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        (rec_id, entry_text, merchant, amount, category, sub_category,
         spend_type, cadence, divide_by, shared_expense, share_ratio) = row

        amount_f = float(amount)
        divide_by = max(1, int(divide_by or 1))
        share_ratio_f = float(share_ratio) if share_ratio is not None else 1.0
        monthly_amount = round(amount_f / divide_by, 2)
        final_amount = round(monthly_amount * share_ratio_f, 2)

        feed_id = insert_data_feed_row(
            conn,
            entry_date, entry_text, sub_category, category, spend_type,
            amount,
            merchant=merchant, vpa=None, upi_ref=None,
            time_period=time_period,
            cadence=cadence or "O",
            divide_by=divide_by,
            monthly_amount=monthly_amount,
            shared_expense=shared_expense or "N",
            share_ratio=share_ratio_f,
            final_amount=final_amount,
            exclude_from_training=True,
        )

        if (shared_expense or "N") == "Y" and entry_date >= _SHARED_SCOPE_START:
            upsert_shared_transaction(
                conn, feed_id,
                amount=amount_f,
                monthly_amount=monthly_amount,
                share_ratio=share_ratio_f,
                entry_date=entry_date,
                merchant=merchant,
                category=category,
                subcategory=sub_category,
                entry_text=entry_text,
            )

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE recurring_transactions SET last_generated = %s WHERE id = %s",
                (today.isoformat(), rec_id),
            )
        conn.commit()

        results.append({"id": rec_id, "feed_id": feed_id, "entry_text": entry_text})

    return results


def create_users_table(conn) -> None:
    """Create the users table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          VARCHAR(20) NOT NULL DEFAULT 'user',
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    conn.commit()


def create_user(conn, username: str, password_hash: str, role: str = "user") -> int:
    """Insert a new user. Returns the new row id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
            (username, password_hash, role),
        )
        row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def get_user_by_username(conn, username: str) -> dict | None:
    """Return {id, username, password_hash, role} or None if not found."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "password_hash": row[2], "role": row[3]}


def username_exists(conn, username: str) -> bool:
    """Return True if a user with this username already exists."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        return cur.fetchone() is not None


def log_email(conn, gmail_message_id: str, status: str, notes: str | None = None) -> None:
    """
    Upsert a row in processed_emails.

    status must be one of: 'success', 'skipped', 'failed'
    """
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO processed_emails (gmail_message_id, processed_at, status, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (gmail_message_id) DO UPDATE
                SET processed_at = EXCLUDED.processed_at,
                    status       = EXCLUDED.status,
                    notes        = EXCLUDED.notes
            """,
            (gmail_message_id, now, status, notes),
        )
    conn.commit()
    logger.debug("Logged email %s as '%s'.", gmail_message_id, status)
