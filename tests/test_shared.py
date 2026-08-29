"""
Tests for the shared_transactions DB functions and Flask blueprint.

DB function tests use the same _make_mock_conn() pattern as test_review.py / test_history.py.
Flask route tests use a test client with db.* functions mocked.
"""

import os
from datetime import date as _date
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask

import db
from shared import shared_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


@pytest.fixture
def app():
    a = Flask(__name__, template_folder=_TEMPLATES)
    a.register_blueprint(shared_bp)
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_conn(fetchone=None, fetchall=None, rowcount=1):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall or []
    mock_cursor.rowcount = rowcount
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# DB: create_shared_transactions_table
# ---------------------------------------------------------------------------

class TestCreateSharedTransactionsTable:
    def test_creates_table_and_backfills(self):
        conn, cur = _make_mock_conn()
        db.create_shared_transactions_table(conn)
        assert cur.execute.call_count == 3  # CREATE+ALTER, INSERT backfill, UPDATE patch
        first_sql = cur.execute.call_args_list[0][0][0]
        assert "CREATE TABLE IF NOT EXISTS shared_transactions" in first_sql
        second_sql = cur.execute.call_args_list[1][0][0]
        assert "INSERT INTO shared_transactions" in second_sql
        assert "ON CONFLICT (history_id) DO NOTHING" in second_sql
        third_sql = cur.execute.call_args_list[2][0][0]
        assert "monthly_amount IS NULL" in third_sql
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DB: upsert_shared_transaction
# ---------------------------------------------------------------------------

class TestUpsertSharedTransaction:
    def _upsert(self, conn, history_id=1, amount=1000.0, monthly_amount=1000.0, share_ratio=0.7,
                entry_date=_date(2026, 5, 1), merchant="Test", category="Food",
                subcategory="Dining", entry_text="Test entry"):
        db.upsert_shared_transaction(
            conn, history_id, amount, monthly_amount, share_ratio,
            entry_date, merchant, category, subcategory, entry_text,
        )

    def test_computes_akhil_share_from_monthly_amount(self):
        conn, cur = _make_mock_conn()
        self._upsert(conn, amount=12000.0, monthly_amount=1000.0, share_ratio=0.7)
        params = cur.execute.call_args[0][1]
        akhil_share = params[4]  # history_id, amount, monthly_amount, share_ratio, akhil_share, ...
        assert akhil_share == 700.0

    def test_computes_aditi_share_from_monthly_amount(self):
        conn, cur = _make_mock_conn()
        self._upsert(conn, amount=12000.0, monthly_amount=1000.0, share_ratio=0.7)
        params = cur.execute.call_args[0][1]
        aditi_share = params[5]
        assert aditi_share == 300.0

    def test_default_balance_is_aditi_share(self):
        conn, cur = _make_mock_conn()
        self._upsert(conn, amount=12000.0, monthly_amount=1000.0, share_ratio=0.7)
        params = cur.execute.call_args[0][1]
        default_balance = params[6]
        assert default_balance == 300.0

    def test_on_conflict_preserves_paid_by_in_sql(self):
        conn, cur = _make_mock_conn()
        self._upsert(conn)
        sql = cur.execute.call_args[0][0]
        assert "ON CONFLICT (history_id) DO UPDATE" in sql
        assert "shared_transactions.paid_by" in sql

    def test_commits(self):
        conn, cur = _make_mock_conn()
        self._upsert(conn)
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DB: delete_shared_transaction
# ---------------------------------------------------------------------------

class TestDeleteSharedTransaction:
    def test_deletes_by_history_id(self):
        conn, cur = _make_mock_conn(rowcount=1)
        result = db.delete_shared_transaction(conn, history_id=42)
        sql, params = cur.execute.call_args[0]
        assert "DELETE FROM shared_transactions WHERE history_id" in sql
        assert params == (42,)
        assert result is True

    def test_returns_false_when_not_found(self):
        conn, cur = _make_mock_conn(rowcount=0)
        result = db.delete_shared_transaction(conn, history_id=99)
        assert result is False

    def test_commits(self):
        conn, cur = _make_mock_conn()
        db.delete_shared_transaction(conn, 1)
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DB: update_shared_row
# ---------------------------------------------------------------------------

class TestUpdateSharedRow:
    # fetchone shape: (paid_by, owed_by, share_ratio, monthly_amount, settled, is_ignored)
    def _existing(self, paid_by="Akhil", owed_by="Aditi", share_ratio=0.7, monthly_amount=1000.0, settled=False, is_ignored=False):
        return (paid_by, owed_by, share_ratio, monthly_amount, settled, is_ignored)

    def test_balance_akhil_paid(self):
        conn, cur = _make_mock_conn(fetchone=self._existing(paid_by="Akhil", share_ratio=0.7, monthly_amount=1000.0))
        result = db.update_shared_row(conn, 1, {"paid_by": "Akhil"})
        assert result["balance"] == 300.0  # aditi_share = 1000 * 0.3

    def test_balance_aditi_paid(self):
        conn, cur = _make_mock_conn(fetchone=self._existing(paid_by="Aditi", share_ratio=0.7, monthly_amount=1000.0))
        result = db.update_shared_row(conn, 1, {"paid_by": "Aditi"})
        assert result["balance"] == 700.0  # akhil_share = 1000 * 0.7

    def test_share_ratio_change_recomputes_shares(self):
        conn, cur = _make_mock_conn(fetchone=self._existing(share_ratio=0.7, monthly_amount=1000.0))
        result = db.update_shared_row(conn, 1, {"share_ratio": 0.5})
        assert result["akhil_share"] == 500.0
        assert result["aditi_share"] == 500.0

    def test_settled_true_sets_settled_at_in_sql(self):
        conn, cur = _make_mock_conn(fetchone=self._existing(settled=False))
        db.update_shared_row(conn, 1, {"settled": True})
        sql = cur.execute.call_args_list[-1][0][0]
        assert "settled_at" in sql
        assert "NOW()" in sql

    def test_settled_false_clears_settled_at(self):
        conn, cur = _make_mock_conn(fetchone=self._existing(settled=True))
        db.update_shared_row(conn, 1, {"settled": False})
        sql = cur.execute.call_args_list[-1][0][0]
        assert "NULL" in sql

    def test_returns_none_when_not_found(self):
        conn, cur = _make_mock_conn(fetchone=None)
        result = db.update_shared_row(conn, 999, {"settled": True})
        assert result is None

    def test_settled_string_true_parsed(self):
        conn, cur = _make_mock_conn(fetchone=self._existing())
        result = db.update_shared_row(conn, 1, {"settled": "true"})
        assert result["settled"] is True


# ---------------------------------------------------------------------------
# DB: get_shared_summary
# ---------------------------------------------------------------------------

class TestGetSharedSummary:
    def test_returns_expected_shape(self):
        # (net_balance, akhil_paid, aditi_paid)
        row = (3000.0, 5000.0, 1000.0)
        conn, cur = _make_mock_conn(fetchone=row)
        result = db.get_shared_summary(conn, 2026)
        assert "net_balance"      in result
        assert "total_akhil_paid" in result
        assert "total_aditi_paid" in result
        assert result["net_balance"]      == 3000.0
        assert result["total_akhil_paid"] == 5000.0

    def test_handles_none_row(self):
        conn, cur = _make_mock_conn(fetchone=None)
        result = db.get_shared_summary(conn, 2026)
        assert result["net_balance"] == 0.0

    def test_summary_sql_excludes_ignored(self):
        conn, cur = _make_mock_conn(fetchone=(0.0, 0.0, 0.0))
        db.get_shared_summary(conn, 2026)
        sql = cur.execute.call_args[0][0]
        assert "is_ignored" in sql


# ---------------------------------------------------------------------------
# DB: get_shared_fy_list
# ---------------------------------------------------------------------------

class TestGetSharedFYList:
    def test_returns_list_of_ints(self):
        conn, cur = _make_mock_conn(fetchall=[(2026,), (2025,)])
        result = db.get_shared_fy_list(conn)
        assert result == [2026, 2025]

    def test_returns_empty_list(self):
        conn, cur = _make_mock_conn(fetchall=[])
        result = db.get_shared_fy_list(conn)
        assert result == []


# ---------------------------------------------------------------------------
# Flask routes â€” auth
# ---------------------------------------------------------------------------

@pytest.fixture
def app_with_auth(app):
    from auth_routes import auth_bp
    app.register_blueprint(auth_bp)
    app.secret_key = "test-secret"
    return app


@pytest.fixture
def user_client(app_with_auth):
    c = app_with_auth.test_client()
    with c.session_transaction() as sess:
        sess["role"] = "user"
        sess["user_id"] = 1
        sess["username"] = "aditi"
    return c


@pytest.fixture
def no_auth_client(app_with_auth):
    """Client with no session and no token; auth_bp registered so url_for works."""
    return app_with_auth.test_client()


class TestSharedAuth:
    def test_no_token_env_allows_access(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("INVITE_CODE", raising=False)
        with patch("db.get_connection") as mock_conn_fn:
            mock_conn, _ = _make_mock_conn(fetchall=[])
            mock_conn_fn.return_value = mock_conn
            with patch("db.get_shared_fy_list", return_value=[2026]):
                resp = client.get("/api/shared/fy-list")
        assert resp.status_code == 200

    def test_token_env_blocks_without_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/shared")
        assert resp.status_code == 401

    def test_correct_token_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        with patch("db.get_connection") as mock_conn_fn:
            mock_conn, _ = _make_mock_conn(fetchall=[])
            mock_conn_fn.return_value = mock_conn
            with patch("db.get_shared_transactions", return_value=[]):
                resp = client.get("/api/shared?fy=2026&token=secret")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Session-based access (user role)
# ---------------------------------------------------------------------------

class TestSharedSessionAuth:
    def test_user_session_grants_page_access(self, user_client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn(fetchall=[])
            mock_fn.return_value = mock_conn
            resp = user_client.get("/api/shared/fy-list")
        assert resp.status_code == 200

    def test_user_session_grants_api_access(self, user_client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn(fetchall=[])
            mock_fn.return_value = mock_conn
            with patch("db.get_shared_transactions", return_value=[]):
                resp = user_client.get("/api/shared?fy=2026")
        assert resp.status_code == 200

    def test_no_session_no_token_blocks_page_api(self, no_auth_client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        resp = no_auth_client.get("/api/shared/fy-list")
        assert resp.status_code == 401

    def test_no_session_no_token_blocks_api(self, no_auth_client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        resp = no_auth_client.get("/api/shared?fy=2026")
        assert resp.status_code == 401

    def test_admin_token_grants_api_access(self, no_auth_client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn(fetchall=[])
            mock_fn.return_value = mock_conn
            with patch("db.get_shared_transactions", return_value=[]):
                resp = no_auth_client.get("/api/shared?fy=2026&token=tok")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Flask routes â€” GET /api/shared
# ---------------------------------------------------------------------------

class TestListShared:
    def test_returns_rows(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        rows = [{"id": 1, "history_id": 10, "paid_by": "Akhil", "owed_by": "Aditi",
                 "amount": 1000.0, "share_ratio": 0.7, "akhil_share": 700.0,
                 "aditi_share": 300.0, "balance": 300.0, "entry_date": "2026-05-01",
                 "merchant": "Swiggy", "category": "Food", "subcategory": "Dining",
                 "entry_text": "Swiggy order", "settled": False, "settled_at": None}]
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn()
            mock_fn.return_value = mock_conn
            with patch("db.get_shared_transactions", return_value=rows):
                resp = client.get("/api/shared?fy=2026")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["paid_by"] == "Akhil"


# ---------------------------------------------------------------------------
# Flask routes â€” PATCH /api/shared/<id>
# ---------------------------------------------------------------------------

class TestPatchShared:
    def test_settled_toggle(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn()
            mock_fn.return_value = mock_conn
            with patch("db.update_shared_row", return_value={"paid_by": "Akhil", "owed_by": "Aditi", "balance": 300.0, "settled": True}):
                resp = client.patch("/api/shared/1",
                                    json={"settled": True},
                                    content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["settled"] is True

    def test_paid_by_change(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn()
            mock_fn.return_value = mock_conn
            with patch("db.update_shared_row", return_value={"paid_by": "Aditi", "owed_by": "Akhil", "balance": 700.0, "settled": False}):
                resp = client.patch("/api/shared/1",
                                    json={"paid_by": "Aditi"},
                                    content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["paid_by"] == "Aditi"

    def test_invalid_paid_by_rejected(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.patch("/api/shared/1", json={"paid_by": "Unknown"}, content_type="application/json")
        assert resp.status_code == 400

    def test_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn()
            mock_fn.return_value = mock_conn
            with patch("db.update_shared_row", return_value=None):
                resp = client.patch("/api/shared/999", json={"settled": True}, content_type="application/json")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Flask routes â€” DELETE /api/shared/<id>
# ---------------------------------------------------------------------------

class TestDeleteShared:
    def test_returns_204(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, cur = _make_mock_conn(rowcount=1)
            mock_fn.return_value = mock_conn
            resp = client.delete("/api/shared/1")
        assert resp.status_code == 204

    def test_not_found_returns_404(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, cur = _make_mock_conn(rowcount=0)
            mock_fn.return_value = mock_conn
            resp = client.delete("/api/shared/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DB: insert_manual_shared_transaction
# ---------------------------------------------------------------------------

class TestInsertManualSharedTransaction:
    def test_computes_akhil_share(self):
        conn, cur = _make_mock_conn(fetchone=(42,))
        db.insert_manual_shared_transaction(
            conn, _date(2026, 5, 1), "Test", "Food", "Dining", 1000.0, 0.7
        )
        params = cur.execute.call_args[0][1]
        # params: amount, monthly_amount, share_ratio, akhil_share, aditi_share, balance, ...
        akhil_share = params[3]
        assert akhil_share == 700.0

    def test_computes_aditi_share(self):
        conn, cur = _make_mock_conn(fetchone=(42,))
        db.insert_manual_shared_transaction(
            conn, _date(2026, 5, 1), "Test", "Food", "Dining", 1000.0, 0.7
        )
        params = cur.execute.call_args[0][1]
        aditi_share = params[4]
        assert aditi_share == 300.0

    def test_balance_akhil_paid(self):
        conn, cur = _make_mock_conn(fetchone=(42,))
        db.insert_manual_shared_transaction(
            conn, _date(2026, 5, 1), None, None, None, 1000.0, 0.7, paid_by="Akhil"
        )
        params = cur.execute.call_args[0][1]
        balance = params[5]
        assert balance == 300.0  # aditi_share

    def test_balance_aditi_paid(self):
        conn, cur = _make_mock_conn(fetchone=(42,))
        db.insert_manual_shared_transaction(
            conn, _date(2026, 5, 1), None, None, None, 1000.0, 0.7, paid_by="Aditi"
        )
        params = cur.execute.call_args[0][1]
        balance = params[5]
        assert balance == 700.0  # akhil_share

    def test_is_manual_in_sql(self):
        conn, cur = _make_mock_conn(fetchone=(1,))
        db.insert_manual_shared_transaction(
            conn, _date(2026, 5, 1), None, None, None, 500.0, 0.5
        )
        sql = cur.execute.call_args[0][0]
        assert "is_manual" in sql
        assert "TRUE" in sql

    def test_returns_id(self):
        conn, cur = _make_mock_conn(fetchone=(99,))
        result = db.insert_manual_shared_transaction(
            conn, _date(2026, 5, 1), None, None, None, 500.0, 0.5
        )
        assert result == 99


# ---------------------------------------------------------------------------
# Flask routes â€” POST /api/shared
# ---------------------------------------------------------------------------

class TestPostShared:
    def _post(self, client, payload):
        return client.post("/api/shared",
                           json=payload,
                           content_type="application/json")

    def test_single_entry_returns_201(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn(fetchone=(1,))
            mock_fn.return_value = mock_conn
            with patch("db.insert_manual_shared_transaction", return_value=1):
                resp = self._post(client, [{"entry_date": "2026-05-01", "monthly_amount": 500}])
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["count"] == 1

    def test_missing_entry_date_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, [{"monthly_amount": 500}])
        assert resp.status_code == 400

    def test_missing_monthly_amount_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, [{"entry_date": "2026-05-01"}])
        assert resp.status_code == 400

    def test_zero_monthly_amount_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, [{"entry_date": "2026-05-01", "monthly_amount": 0}])
        assert resp.status_code == 400

    def test_multiple_entries(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn(fetchone=(1,))
            mock_fn.return_value = mock_conn
            with patch("db.insert_manual_shared_transaction", side_effect=[1, 2, 3]):
                resp = self._post(client, [
                    {"entry_date": "2026-05-01", "monthly_amount": 100},
                    {"entry_date": "2026-05-02", "monthly_amount": 200},
                    {"entry_date": "2026-05-03", "monthly_amount": 300},
                ])
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 3


# ---------------------------------------------------------------------------
# DB: insert_payment_shared_transaction
# ---------------------------------------------------------------------------

class TestInsertPaymentSharedTransaction:
    def test_balance_equals_amount(self):
        conn, cur = _make_mock_conn(fetchone=(10,))
        db.insert_payment_shared_transaction(
            conn, _date(2026, 6, 1), "Aditi", "Akhil", 5000.0, "June"
        )
        params = cur.execute.call_args[0][1]
        # (amount, monthly_amount, balance, paid_by, owed_by, entry_date, note)
        amount  = params[0]
        monthly = params[1]
        balance = params[2]
        assert amount == 5000.0
        assert monthly == 5000.0
        assert balance == 5000.0

    def test_is_payment_in_sql(self):
        conn, cur = _make_mock_conn(fetchone=(1,))
        db.insert_payment_shared_transaction(
            conn, _date(2026, 6, 1), "Aditi", "Akhil", 500.0, None
        )
        sql = cur.execute.call_args[0][0]
        assert "is_payment" in sql
        assert "TRUE" in sql

    def test_returns_id(self):
        conn, cur = _make_mock_conn(fetchone=(77,))
        result = db.insert_payment_shared_transaction(
            conn, _date(2026, 6, 1), "Aditi", "Akhil", 500.0, None
        )
        assert result == 77


# ---------------------------------------------------------------------------
# Flask routes â€” POST /api/shared/payment
# ---------------------------------------------------------------------------

class TestPostPayment:
    def _post(self, client, payload):
        return client.post("/api/shared/payment",
                           json=payload,
                           content_type="application/json")

    def test_valid_payload_returns_201(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn(fetchone=(1,))
            mock_fn.return_value = mock_conn
            with patch("db.insert_payment_shared_transaction", return_value=1):
                resp = self._post(client, {"entry_date": "2026-06-01", "paid_by": "Aditi", "amount": 5000})
        assert resp.status_code == 201
        assert resp.get_json()["ok"] is True

    def test_missing_entry_date_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, {"paid_by": "Aditi", "amount": 5000})
        assert resp.status_code == 400

    def test_invalid_paid_by_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, {"entry_date": "2026-06-01", "paid_by": "Bob", "amount": 5000})
        assert resp.status_code == 400

    def test_zero_amount_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, {"entry_date": "2026-06-01", "paid_by": "Aditi", "amount": 0})
        assert resp.status_code == 400

    def test_same_person_payer_payee_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = self._post(client, {"entry_date": "2026-06-01", "paid_by": "Aditi", "owed_by": "Aditi", "amount": 100})
        assert resp.status_code == 400

    def test_owed_by_auto_set(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        captured = {}
        def fake_insert(conn, entry_date, paid_by, owed_by, amount, note):
            captured['owed_by'] = owed_by
            return 1
        with patch("db.get_connection") as mock_fn:
            mock_conn, _ = _make_mock_conn()
            mock_fn.return_value = mock_conn
            with patch("db.insert_payment_shared_transaction", side_effect=fake_insert):
                self._post(client, {"entry_date": "2026-06-01", "paid_by": "Aditi", "amount": 100})
        assert captured.get('owed_by') == 'Akhil'
