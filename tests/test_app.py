"""
Smoke tests for the Flask trigger endpoint and blueprint wiring.

All external I/O (Gmail API, DB, GCS, email sending) is mocked.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


_EMPTY_SUMMARY = {"processed": 0, "skipped": 0, "failed": 0, "transactions": []}
_ONE_TXN_SUMMARY = {
    "processed": 1, "skipped": 0, "failed": 0,
    "transactions": [{
        "date": datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
        "format": "upi", "type": "debit", "amount": 250.0, "merchant": "Swiggy",
    }],
}
_FAILED_SUMMARY = {"processed": 0, "skipped": 0, "failed": 1, "transactions": []}


@pytest.fixture
def client(monkeypatch):
    import app as flask_app  # load_dotenv() runs on first import; delenv must come after
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("INVITE_CODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    flask_app.app.config["TESTING"] = True
    flask_app.app.secret_key = "test-secret"
    return flask_app.app.test_client()


class TestTriggerEndpoint:
    def test_returns_200_with_no_transactions(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_EMPTY_SUMMARY), \
             patch("app.run_categorization", return_value="ok"), \
             patch("app.run_parser_tests", return_value="PASS  all"), \
             patch("app.send_summary_email"):
            resp = client.get("/trigger")
        assert resp.status_code == 200

    def test_status_ok_when_no_failures(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_ONE_TXN_SUMMARY), \
             patch("app.run_categorization", return_value="ok"), \
             patch("app.run_parser_tests", return_value="PASS  all"), \
             patch("app.send_summary_email"):
            resp = client.get("/trigger")
        assert resp.get_json()["status"] == "ok"

    def test_status_partial_failure_when_failures(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_FAILED_SUMMARY), \
             patch("app.run_categorization", return_value="ok"), \
             patch("app.run_parser_tests", return_value="PASS  all"), \
             patch("app.send_summary_email"):
            resp = client.get("/trigger")
        assert resp.get_json()["status"] == "partial_failure"

    def test_response_includes_counts(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_ONE_TXN_SUMMARY), \
             patch("app.run_categorization", return_value="ok"), \
             patch("app.run_parser_tests", return_value="PASS  all"), \
             patch("app.send_summary_email"):
            data = client.get("/trigger").get_json()
        assert data["processed"] == 1
        assert data["skipped"] == 0
        assert data["failed"] == 0

    def test_categorization_failure_does_not_break_response(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_EMPTY_SUMMARY), \
             patch("app.run_categorization", return_value="FAILED: GCS down"), \
             patch("app.run_parser_tests", return_value="PASS  all"), \
             patch("app.send_summary_email"):
            resp = client.get("/trigger")
        assert resp.status_code == 200

    def test_categorization_status_passed_to_send_summary_email(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_EMPTY_SUMMARY), \
             patch("app.run_categorization", return_value="FAILED: GCS down"), \
             patch("app.run_parser_tests", return_value="PASS"), \
             patch("app.send_summary_email") as mock_send:
            client.get("/trigger")
        _, kwargs = mock_send.call_args
        assert kwargs.get("categorization_status") == "FAILED: GCS down"

    def test_run_categorization_called_on_every_trigger(self, client):
        with patch("app._build_gmail_service", return_value=MagicMock()), \
             patch("app.main", return_value=_EMPTY_SUMMARY), \
             patch("app.run_categorization", return_value="ok") as mock_cat, \
             patch("app.run_parser_tests", return_value="PASS"), \
             patch("app.send_summary_email"):
            client.get("/trigger")
            client.get("/trigger")
        assert mock_cat.call_count == 2


class TestBlueprintWiring:
    def test_api_categories_accessible(self, client):
        resp = client.get("/api/categories")
        assert resp.status_code == 200

    def test_token_auth_enforced_on_categories(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        c = flask_app.app.test_client()
        assert c.get("/api/categories").status_code == 401
        assert c.get("/api/categories?token=secret").status_code == 200

    def test_trigger_blocked_without_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        monkeypatch.setenv("INVITE_CODE", "inv")
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        c = flask_app.app.test_client()
        assert c.get("/trigger").status_code == 401


# ---------------------------------------------------------------------------
# GET / — smart redirect
# ---------------------------------------------------------------------------

class TestIndexRedirect:
    def test_no_auth_redirects_to_login(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_admin_token_redirects_to_view(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        resp = client.get("/?token=tok", follow_redirects=False)
        assert resp.status_code == 302
        assert "/view" in resp.headers["Location"]

    def test_user_session_redirects_to_shared(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        monkeypatch.setenv("INVITE_CODE", "inv")
        with client.session_transaction() as sess:
            sess["role"] = "user"
            sess["user_id"] = 1
            sess["username"] = "aditi"
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/shared" in resp.headers["Location"]
