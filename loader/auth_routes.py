"""
Flask Blueprint for user authentication.

Routes:
  GET  /login    — login page
  POST /login    — authenticate and set session cookie
  GET  /logout   — clear session and redirect to /login
  GET  /register — registration page
  POST /register — create user account (requires INVITE_CODE)
"""

import os

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db
from token_auth import _auth_disabled, _is_valid_admin_token

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/me")
def me():
    if session.get("role") in ("user", "admin"):
        return jsonify({"username": session["username"], "role": session["role"]})
    if _auth_disabled() or _is_valid_admin_token():
        return jsonify({"username": "Admin", "role": "admin"})
    return jsonify({"error": "Unauthenticated"}), 401


@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("login.html", error="Username and password are required."), 400

    conn = db.get_connection()
    try:
        user = db.get_user_by_username(conn, username)
    finally:
        conn.close()

    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid username or password."), 401

    session.permanent = True
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["username"] = user["username"]
    if user["role"] == "admin":
        return redirect("/view")
    return redirect("/shared")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("register.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    invite_code = request.form.get("invite_code", "").strip()

    if not username or not password or not invite_code:
        return render_template("register.html", error="All fields are required."), 400

    expected_code = os.environ.get("INVITE_CODE", "")
    if not expected_code or invite_code != expected_code:
        return render_template("register.html", error="Invalid invite code."), 400

    if len(password) < 8:
        return render_template("register.html", error="Password must be at least 8 characters."), 400

    conn = db.get_connection()
    try:
        if db.username_exists(conn, username):
            return render_template("register.html", error="Username already taken."), 400
        db.create_user(conn, username, generate_password_hash(password))
    finally:
        conn.close()

    return redirect(url_for("auth.login_page"))
