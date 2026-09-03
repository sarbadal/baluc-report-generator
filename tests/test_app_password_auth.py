from __future__ import annotations

from pathlib import Path

from flask import Blueprint
from flask import Flask

from app.blueprints.auth import auth_blueprint
from app.blueprints.auth import register_app_password_gate


def _make_app(app_password: str = "secret") -> Flask:
    template_folder = Path(__file__).resolve().parents[1] / "app" / "templates"
    app = Flask(__name__, template_folder=str(template_folder))
    app.config.update(SECRET_KEY="test-secret", APP_PASSWORD=app_password, TESTING=True)
    app.register_blueprint(auth_blueprint)
    home_blueprint = Blueprint("home", __name__)

    @home_blueprint.route("/")
    def home():
        return "home"

    @home_blueprint.route("/report-generator")
    def report_generator_page():
        return "report generator"

    app.register_blueprint(home_blueprint)

    @app.context_processor
    def template_globals() -> dict[str, object]:
        return {
            "app_password_enabled": bool(app_password.strip()),
            "current_year": 2026,
            "static_asset": lambda filename: f"/static/{filename}",
        }

    register_app_password_gate(app)
    return app


def test_password_gate_redirects_anonymous_users_to_login() -> None:
    client = _make_app().test_client()

    response = client.get("/?report=latest")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login?next=/?report%3Dlatest")


def test_login_rejects_wrong_password() -> None:
    client = _make_app().test_client()

    response = client.post("/auth/login", data={"password": "wrong"})

    assert response.status_code == 200
    assert b"Incorrect password." in response.data


def test_login_accepts_configured_password_and_allows_requests() -> None:
    client = _make_app().test_client()

    login_response = client.post(
        "/auth/login",
        data={"password": "secret", "next": "/"},
    )

    assert login_response.status_code == 302
    assert login_response.headers["Location"].endswith("/")

    response = client.get("/")
    assert response.status_code == 200
    assert response.data == b"home"


def test_password_gate_is_disabled_when_env_password_is_blank() -> None:
    client = _make_app(app_password="").test_client()

    response = client.get("/")


    assert response.status_code == 200
    assert response.data == b"home"