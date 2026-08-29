"""
Tests for the review Flask blueprint.

Auth and /api/categories tests use the real rules.json (no DB needed).
Batch API route tests mock db.get_connection() to avoid requiring a real DB.
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest
from flask import Flask

from review import review_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")
_RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "categorizer", "config", "rules.json")


@pytest.fixture
def app():
    a = Flask(__name__, template_folder=_TEMPLATES)
    a.register_blueprint(review_bp)
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_conn(fetchone=None, fetchall=None, rowcount=1):
    """Return a mock psycopg2 connection with a configurable cursor."""
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
    def test_no_token_env_allows_access(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.get("/api/categories")
        assert resp.status_code == 200

    def test_token_env_set_blocks_without_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/categories")
        assert resp.status_code == 401

    def test_token_env_set_blocks_wrong_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/categories?token=wrong")
        assert resp.status_code == 401

    def test_correct_query_param_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/categories?token=secret")
        assert resp.status_code == 200

    def test_correct_bearer_header_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/categories", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_raw_token_in_auth_header_also_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/categories", headers={"Authorization": "secret"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/categories
# ---------------------------------------------------------------------------

class TestGetCategories:
    def test_returns_200(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        resp = client.get("/api/categories")
        assert resp.status_code == 200

    def test_response_has_categories_and_types_keys(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert "categories" in data
        assert "types" in data

    def test_categories_is_dict_of_lists(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert isinstance(data["categories"], dict)
        for cat, subs in data["categories"].items():
            assert isinstance(cat, str)
            assert isinstance(subs, list)

    def test_categories_nonempty_from_rules_json(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert len(data["categories"]) > 0

    def test_types_fallback_when_no_db(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert isinstance(data["types"], list)
        assert len(data["types"]) > 0

    def test_categories_require_token_when_set(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        resp = client.get("/api/categories")
        assert resp.status_code == 401

    def test_categories_accessible_with_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        resp = client.get("/api/categories?token=tok")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/batches
# ---------------------------------------------------------------------------

_CREATED_AT = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)


class TestListBatches:
    def test_returns_200(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn(
            fetchall=[(1, 10, "pending", _CREATED_AT)]
        )
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.get("/api/batches")
        assert resp.status_code == 200

    def test_returns_list_shape(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(
            fetchall=[(1, 10, "pending", _CREATED_AT), (2, 5, "reviewed", _CREATED_AT)]
        )
        with patch("review.db.get_connection", return_value=mock_conn):
            data = client.get("/api/batches").get_json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["status"] == "pending"

    def test_excludes_complete_by_default(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn(fetchall=[])
        with patch("review.db.get_connection", return_value=mock_conn):
            client.get("/api/batches")
        sql = mock_cursor.execute.call_args[0][0]
        assert "status != 'complete'" in sql or "status !=" in sql

    def test_includes_complete_with_flag(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn(fetchall=[])
        with patch("review.db.get_connection", return_value=mock_conn):
            client.get("/api/batches?include_complete=1")
        sql = mock_cursor.execute.call_args[0][0]
        assert "status" not in sql or "!=" not in sql


class TestGetBatch:
    def _make_batch_conn(self, batch_row, item_rows):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = batch_row
        mock_cursor.fetchall.return_value = item_rows
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn

    def test_returns_200_for_existing_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        batch = (1, 2, "pending", _CREATED_AT)
        items = [
            (101, "Food", "Eating Out", "Expense", 0.9, "ml",
             "Food", "Eating Out", "Expense",
             _CREATED_AT, "Rs.100", 100.0, "Swiggy", None, "O", 1, "N", 1.0),
        ]
        mock_conn = self._make_batch_conn(batch, items)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.get("/api/batches/1")
        assert resp.status_code == 200

    def test_response_has_batch_and_items(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        batch = (1, 1, "pending", _CREATED_AT)
        items = [
            (101, "Food", "Eating Out", "Expense", 0.9, "ml",
             "Food", "Eating Out", "Expense",
             _CREATED_AT, "Rs.100", 100.0, "Swiggy", None, "O", 1, "N", 1.0),
        ]
        mock_conn = self._make_batch_conn(batch, items)
        with patch("review.db.get_connection", return_value=mock_conn):
            data = client.get("/api/batches/1").get_json()
        assert "batch" in data
        assert "items" in data
        assert data["batch"]["id"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["transaction_id"] == 101

    def test_returns_404_for_missing_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=None)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.get("/api/batches/999")
        assert resp.status_code == 404

    def test_item_financial_fields_present(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        batch = (1, 1, "pending", _CREATED_AT)
        items = [
            (101, "Food", "Eating Out", "Expense", 0.9, "ml",
             "Food", "Eating Out", "Expense",
             _CREATED_AT, "Rs.100", 100.0, "Swiggy", None, "M", 2, "Y", 0.5),
        ]
        mock_conn = self._make_batch_conn(batch, items)
        with patch("review.db.get_connection", return_value=mock_conn):
            data = client.get("/api/batches/1").get_json()
        item = data["items"][0]
        assert item["cadence"] == "M"
        assert item["divide_by"] == 2
        assert item["shared_expense"] == "Y"
        assert item["share_ratio"] == 0.5


# ---------------------------------------------------------------------------
# PATCH /api/batches/<id>/items/<txn_id>
# ---------------------------------------------------------------------------

class TestUpdateItem:
    def test_returns_200_on_success(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(rowcount=1)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.patch(
                "/api/batches/1/items/101",
                json={"category": "Food", "subcategory": "Eating Out", "type": "Expense",
                      "cadence": "O", "divide_by": 1, "shared_expense": "N", "share_ratio": 1.0},
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_returns_404_when_item_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(rowcount=0)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.patch(
                "/api/batches/1/items/999",
                json={"category": "Food", "subcategory": "Eating Out", "type": "Expense",
                      "cadence": "O", "divide_by": 1, "shared_expense": "N", "share_ratio": 1.0},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/batches/<id>/items/<txn_id>
# ---------------------------------------------------------------------------

class TestDeleteItem:
    def test_returns_200_on_success(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(rowcount=1)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.delete("/api/batches/1/items/101")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_returns_404_when_item_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(rowcount=0)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.delete("/api/batches/1/items/999")
        assert resp.status_code == 404

    def test_inserts_into_exclusions_on_delete(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn(rowcount=1)
        with patch("review.db.get_connection", return_value=mock_conn):
            client.delete("/api/batches/1/items/101")
        sql_calls = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "transaction_exclusions" in sql_calls


# ---------------------------------------------------------------------------
# DELETE /api/batches/<id>
# ---------------------------------------------------------------------------

class TestDeleteBatch:
    def test_deletes_pending_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=("pending",), rowcount=1)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.delete("/api/batches/1")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_deletes_reviewed_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=("reviewed",), rowcount=1)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.delete("/api/batches/1")
        assert resp.status_code == 200

    def test_rejects_complete_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=("complete",))
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.delete("/api/batches/1")
        assert resp.status_code == 400

    def test_returns_404_for_missing_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=None)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.delete("/api/batches/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/batches/<id>/mark-reviewed
# ---------------------------------------------------------------------------

class TestMarkReviewed:
    def test_transitions_pending_to_reviewed(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=("pending",))
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.post("/api/batches/1/mark-reviewed")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "reviewed"

    def test_idempotent_if_already_reviewed(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=("reviewed",))
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.post("/api/batches/1/mark-reviewed")
        assert resp.status_code == 200

    def test_rejects_complete_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=("complete",))
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.post("/api/batches/1/mark-reviewed")
        assert resp.status_code == 400

    def test_returns_404_for_missing_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchone=None)
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.post("/api/batches/999/mark-reviewed")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/batches/<id>/complete
# ---------------------------------------------------------------------------

class TestCompleteBatch:
    def _make_complete_conn(self, status="reviewed"):
        mock_cursor = MagicMock()
        call_count = [0]

        def fetchone_side():
            call_count[0] += 1
            if call_count[0] == 1:
                return (status,)
            return None

        mock_cursor.fetchone.side_effect = fetchone_side
        mock_cursor.fetchall.return_value = []
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn

    def test_returns_200_for_reviewed_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn = self._make_complete_conn("reviewed")
        with patch("review.db.get_connection", return_value=mock_conn), \
             patch("review.db.create_data_feed_table"), \
             patch("review.db.insert_data_feed_row", return_value=True), \
             patch("review._trigger_retraining"):
            resp = client.post("/api/batches/1/complete")
        assert resp.status_code == 200
        assert "inserted" in resp.get_json()

    def test_rejects_non_reviewed_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn = self._make_complete_conn("pending")
        with patch("review.db.get_connection", return_value=mock_conn), \
             patch("review.db.create_data_feed_table"):
            resp = client.post("/api/batches/1/complete")
        assert resp.status_code == 400

    def test_returns_404_for_missing_batch(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        with patch("review.db.get_connection", return_value=mock_conn):
            resp = client.post("/api/batches/999/complete")
        assert resp.status_code == 404
