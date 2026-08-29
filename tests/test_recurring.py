"""
Tests for the recurring transactions Flask blueprint and db helpers.

Auth tests use no DB.
API route tests mock db.get_connection() to avoid requiring a real DB.
generate_recurring_entries tests mock the connection directly.
"""

import os
from datetime import date as _date
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask

from recurring import recurring_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


@pytest.fixture
def app():
    a = Flask(__name__, template_folder=_TEMPLATES)
    a.register_blueprint(recurring_bp)
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
# Auth
# ---------------------------------------------------------------------------

class TestRequireToken:
    def test_no_token_env_allows_page(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/recurring")
        assert resp.status_code == 200

    def test_token_env_blocks_page_without_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/recurring")
        assert resp.status_code == 401

    def test_correct_query_param_grants_page(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/recurring?token=secret")
        assert resp.status_code == 200

    def test_correct_bearer_header_grants_page(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/recurring", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_api_list_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.get("/api/recurring").status_code == 401

    def test_api_create_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.post("/api/recurring", json={}).status_code == 401

    def test_api_generate_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.post("/api/recurring/generate").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/recurring
# ---------------------------------------------------------------------------

class TestListRecurring:
    def test_returns_200_and_list(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        sample = [
            {"id": 1, "entry_text": "Groww SIP", "amount": 5000.0, "active": True},
            {"id": 2, "entry_text": "RD Transfer", "amount": 2000.0, "active": True},
        ]
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.get_recurring_transactions", return_value=sample):
            resp = client.get("/api/recurring")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_returns_empty_list(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.get_recurring_transactions", return_value=[]):
            data = client.get("/api/recurring").get_json()
        assert data == []


# ---------------------------------------------------------------------------
# POST /api/recurring
# ---------------------------------------------------------------------------

class TestCreateRecurring:
    def test_creates_returns_201(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.upsert_recurring_transaction", return_value=7) as mock_upsert:
            resp = client.post("/api/recurring", json={"entry_text": "Groww SIP", "amount": 5000})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["id"] == 7

    def test_rejects_missing_entry_text(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.post("/api/recurring", json={"amount": 5000})
        assert resp.status_code == 400

    def test_rejects_missing_amount(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.post("/api/recurring", json={"entry_text": "Groww SIP"})
        assert resp.status_code == 400

    def test_defaults_active_to_true(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def capture(conn, data, row_id=None):
            captured.update(data)
            return 1
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.upsert_recurring_transaction", side_effect=capture):
            client.post("/api/recurring", json={"entry_text": "Test", "amount": 100})
        assert captured.get("active") is True

    def test_defaults_divide_by_to_1(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def capture(conn, data, row_id=None):
            captured.update(data)
            return 1
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.upsert_recurring_transaction", side_effect=capture):
            client.post("/api/recurring", json={"entry_text": "Test", "amount": 100})
        assert captured.get("divide_by") == 1


# ---------------------------------------------------------------------------
# PUT /api/recurring/<id>
# ---------------------------------------------------------------------------

class TestUpdateRecurring:
    def test_returns_200_on_valid_update(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.upsert_recurring_transaction", return_value=3):
            resp = client.put("/api/recurring/3", json={"entry_text": "Updated", "amount": 1000})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_returns_404_when_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.upsert_recurring_transaction", return_value=None):
            resp = client.put("/api/recurring/99", json={"entry_text": "X", "amount": 1})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/recurring/<id>
# ---------------------------------------------------------------------------

class TestDeleteRecurring:
    def test_delete_returns_204(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.delete_recurring_transaction", return_value=True):
            resp = client.delete("/api/recurring/1")
        assert resp.status_code == 204

    def test_delete_returns_404_when_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.delete_recurring_transaction", return_value=False):
            resp = client.delete("/api/recurring/99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/recurring/generate (endpoint)
# ---------------------------------------------------------------------------

class TestGenerateEndpoint:
    def test_returns_200_with_count(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        generated = [{"id": 1, "feed_id": 10, "entry_text": "Groww SIP"}]
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.generate_recurring_entries", return_value=generated):
            resp = client.post("/api/recurring/generate")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["count"] == 1
        assert len(data["generated"]) == 1

    def test_returns_empty_when_nothing_due(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.generate_recurring_entries", return_value=[]):
            resp = client.post("/api/recurring/generate")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 0

    def test_custom_date_param_forwarded(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def capture(conn, today=None):
            captured["today"] = today
            return []
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.generate_recurring_entries", side_effect=capture):
            client.post("/api/recurring/generate?date=2026-01-01")
        assert captured["today"] == _date(2026, 1, 1)

    def test_invalid_date_param_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.post("/api/recurring/generate?date=not-a-date")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# db.generate_recurring_entries â€” unit tests (no Flask, no real DB)
# ---------------------------------------------------------------------------

class TestGenerateRecurringEntries:
    """Direct tests of the db function using a mocked connection."""

    def _make_conn_with_rows(self, rows):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_no_active_rows_returns_empty_list(self):
        import db
        mock_conn, _ = self._make_conn_with_rows([])
        result = db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert result == []

    def test_generates_one_row_calls_insert(self):
        import db
        row = (1, "Groww SIP", "Groww", Decimal("5000.00"),
               "Investment", "SIP", "Investment", "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = self._make_conn_with_rows([row])
        with patch.object(db, "insert_data_feed_row", return_value=42) as mock_insert:
            result = db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["feed_id"] == 42
        assert result[0]["entry_text"] == "Groww SIP"
        mock_insert.assert_called_once()

    def test_entry_date_is_first_of_month(self):
        import db
        row = (1, "SIP", "Groww", Decimal("5000.00"),
               "Investment", "SIP", "Investment", "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, entry_date, *args, **kwargs):
            captured["entry_date"] = entry_date
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 15))
        assert captured["entry_date"] == _date(2026, 6, 1)

    def test_time_period_matches_first_of_month(self):
        import db
        row = (1, "SIP", None, Decimal("1000.00"), None, None, None, "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, entry_date, *args, **kwargs):
            captured["time_period"] = kwargs.get("time_period")
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 3))
        assert captured["time_period"] == "Jun-2026"

    def test_exclude_from_training_is_true(self):
        import db
        row = (1, "SIP", None, Decimal("1000.00"), None, None, None, "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, *args, **kwargs):
            captured["exclude"] = kwargs.get("exclude_from_training")
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert captured["exclude"] is True

    def test_computes_monthly_and_final_amount(self):
        import db
        row = (1, "Annual Plan", None, Decimal("12000.00"),
               "Expense", "Subscription", "Expense", "A", 12, "N", Decimal("0.5"))
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, *args, **kwargs):
            captured["monthly_amount"] = kwargs.get("monthly_amount")
            captured["final_amount"] = kwargs.get("final_amount")
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert captured["monthly_amount"] == 1000.0
        assert captured["final_amount"] == 500.0

    def test_last_generated_updated_after_insert(self):
        import db
        row = (7, "RD Transfer", None, Decimal("2000.00"),
               "Saving", "RD", "Saving", "O", 1, "N", Decimal("1.0"))
        mock_conn, mock_cursor = self._make_conn_with_rows([row])
        with patch.object(db, "insert_data_feed_row", return_value=99):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        update_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("last_generated" in c for c in update_calls)

    def test_idempotency_sql_uses_date_trunc(self):
        import db
        mock_conn, mock_cursor = self._make_conn_with_rows([])
        db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        select_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "DATE_TRUNC" in select_sql
        assert "last_generated" in select_sql
