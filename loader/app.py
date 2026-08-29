"""
Flask entry point for the ExpTrack Cloud Run service.

Cloud Scheduler hits GET / daily at 9 PM IST, which triggers Gmail polling,
categorization, and a nightly summary email.

For local development:
    cd loader && PORT=5000 python app.py
"""

import os
import threading

from dotenv import load_dotenv
from datetime import date as _date, timedelta
from flask import Flask, abort, jsonify, redirect, send_from_directory, url_for
from auth_routes import auth_bp
from token_auth import require_admin, _is_valid_admin_token, _is_valid_user_session
from history import history_bp
from review import review_bp, is_retraining
from recurring import recurring_bp
from shared import shared_bp
from werkzeug.exceptions import HTTPException
from gmail_poller import (
    _build_gmail_service,
    main,
    run_categorization,
    run_parser_tests,
    send_summary_email,
)

load_dotenv()

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_project_root, "templates"))
_static_dist = os.path.join(_project_root, "static", "dist")

import logging as _logging
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    _logging.getLogger(__name__).warning("SECRET_KEY not set — using insecure default. Set it in production.")
    _secret = "dev-secret-change-me"
app.secret_key = _secret
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SECRET_KEY") is not None
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

app.register_blueprint(auth_bp)
app.register_blueprint(review_bp)
app.register_blueprint(history_bp)
app.register_blueprint(recurring_bp)
app.register_blueprint(shared_bp)

import db as _db
try:
    _startup_conn = _db.get_connection()
    _db.create_tables(_startup_conn)
    _db.create_data_feed_table(_startup_conn)
    _db.create_recurring_table(_startup_conn)
    _db.create_settings_table(_startup_conn)
    _db.create_shared_transactions_table(_startup_conn)
    _db.create_users_table(_startup_conn)
    _startup_conn.close()
except Exception as _e:
    _logging.getLogger(__name__).warning("DB table setup skipped at startup: %s", _e)

_trigger_lock = threading.Lock()


@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({"error": e.description, "code": e.code}), e.code


@app.route("/")
def index():
    if _is_valid_user_session():
        return redirect("/shared")
    if _is_valid_admin_token():
        return redirect("/view")
    return redirect(url_for("auth.login_page"))


@app.route("/trigger", methods=["GET", "POST"])
@require_admin
def trigger():
    if not _trigger_lock.acquire(blocking=False):
        _logging.getLogger(__name__).warning("Duplicate /trigger request — pipeline already running, ignoring.")
        return jsonify({"status": "skipped", "message": "Pipeline already running."}), 200

    try:
        return _run_trigger()
    finally:
        _trigger_lock.release()


def _run_trigger():
    service = _build_gmail_service()
    summary = main(service)
    if is_retraining():
        _logging.getLogger(__name__).info("Skipping categorization — model retraining in progress.")
        cat_status = "skipped (model retraining in progress)"
    else:
        cat_status = run_categorization()
    test_output = run_parser_tests()

    _recurring_count = 0
    if _date.today().day == 1:
        try:
            _rec_conn = _db.get_connection()
            _recurring_count = len(_db.generate_recurring_entries(_rec_conn))
            _rec_conn.close()
        except Exception as _re:
            _logging.getLogger(__name__).warning("Recurring generation failed: %s", _re)

    send_summary_email(service, summary, test_output, categorization_status=cat_status)

    no_transactions = summary["processed"] == 0 and summary["skipped"] == 0
    return jsonify({
        "status": "ok" if summary["failed"] == 0 else "partial_failure",
        "processed": summary["processed"],
        "skipped": summary["skipped"],
        "failed": summary["failed"],
        "recurring_generated": _recurring_count,
        "message": (
            "No new transactions found."
            if no_transactions
            else f"{summary['processed']} transaction(s) processed."
        ),
    }), 200


@app.route("/<path:path>")
def spa_catch_all(path):
    if path.startswith("api/") or path in ("login", "logout", "register", "trigger"):
        abort(404)
    candidate = os.path.join(_static_dist, path)
    if os.path.isfile(candidate):
        return send_from_directory(_static_dist, path)
    index_path = os.path.join(_static_dist, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(_static_dist, "index.html")
    abort(404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
