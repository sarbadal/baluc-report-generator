"""Application-level password authentication."""

from __future__ import annotations

from hmac import compare_digest

from flask import Blueprint
from flask import current_app
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for


auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")
SESSION_AUTH_KEY = "app_password_authenticated"
EXEMPT_ENDPOINTS = {"auth.login", "auth.logout", "static"}


def register_app_password_gate(app) -> None:
    """Require the configured app password before serving application endpoints."""

    @app.before_request
    def require_app_password():
        expected_password = _configured_app_password()
        if not expected_password or request.endpoint in EXEMPT_ENDPOINTS:
            return None

        if session.get(SESSION_AUTH_KEY) is True:
            return None

        return redirect(url_for("auth.login", next=_current_path_with_query()))


@auth_blueprint.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate a user with the app-level password."""
    expected_password = _configured_app_password()
    if not expected_password:
        return redirect(url_for("home.home"))

    next_url = _safe_next_path(request.values.get("next"))
    error = None

    if request.method == "POST":
        submitted_password = request.form.get("password", "")
        if compare_digest(submitted_password, expected_password):
            session[SESSION_AUTH_KEY] = True
            return redirect(next_url)
        error = "Incorrect password."

    return render_template("auth/login.html", error=error, next_url=next_url)


@auth_blueprint.route("/logout", methods=["POST"])
def logout():
    """Clear app-level password authentication from the current session."""
    session.pop(SESSION_AUTH_KEY, None)
    if _configured_app_password():
        return redirect(url_for("auth.login"))
    return redirect(url_for("home.home"))


def _configured_app_password() -> str:
    return str(current_app.config.get("APP_PASSWORD", "")).strip()


def _current_path_with_query() -> str:
    if request.query_string:
        return f"{request.path}?{request.query_string.decode('utf-8', errors='ignore')}"
    return request.path


def _safe_next_path(raw_next: str | None) -> str:
    if raw_next and raw_next.startswith("/") and not raw_next.startswith("//"):
        return raw_next
    if "home.home" in current_app.view_functions:
        return url_for("home.home")
    return "/"