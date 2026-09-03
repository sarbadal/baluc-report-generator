"""Application package and factory.

This module exposes the Flask application factory used by the runtime entry
point and by tests.
"""

from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask
from flask import url_for
from dotenv import load_dotenv


IST_TZ = ZoneInfo("Asia/Kolkata")

# Ensure local runs (python main.py) load the project-root .env reliably.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)


def _load_selected_env_keys(dotenv_path: Path, keys: set[str]) -> None:
    """Load selected KEY=VALUE pairs from .env, tolerating unrelated multiline values."""
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    in_multiline = False
    multiline_quote = ""
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if in_multiline:
            if line.endswith(multiline_quote):
                in_multiline = False
                multiline_quote = ""
            continue

        if line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and value[0] in {'"', "'"} and (len(value) == 1 or value[-1] != value[0]):
            in_multiline = True
            multiline_quote = value[0]

        if key not in keys:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


_load_selected_env_keys(
    _ENV_PATH,
    {
        "APP_ENV",
        "ENV_TYPE",
        "APP_PASSWORD",
        "REPORT_TRIGGER_FUNCTION_URL",
        "REPORT_TRIGGER_TIMEOUT_SECONDS",
        "REPORT_TRIGGER_AUTH_TOKEN",
        "REPORT_TRIGGER_CA_BUNDLE_PATH",
        "REPORT_TRIGGER_INSECURE_SKIP_VERIFY",
        "REPORT_TRIGGER_DISABLE_SYSTEM_PROXY",
    },
)

from app.blueprints.auth import register_app_password_gate
from app.blueprints import register_blueprints
from app.config import get_config
from app.core.logging import configure_logging
from app.extensions import init_extensions
from app.report_factory import ReportJobManager
from app.services import GCSReportStorageRepository
from app.services import GCSStorageClientProvider


def create_app(config_object: str | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__, instance_relative_config=True)

    # Load default settings, then optionally override via an explicit config path.
    app.config.from_object(get_config())
    if config_object:
        app.config.from_object(config_object)

    if app.config.get("USE_GCS_STATIC_ASSETS") and not app.config.get("STATIC_ASSET_BASE_URL"):
        static_bucket = str(app.config.get("STATIC_BUCKET") or os.getenv("STATIC_BUCKET", "")).strip()
        static_prefix = str(app.config.get("STATIC_GCS_PREFIX", "static")).strip().strip("/")
        if static_bucket:
            app.config["STATIC_ASSET_BASE_URL"] = (
                f"https://storage.googleapis.com/{static_bucket}/{static_prefix}"
            )

    configure_logging(app)
    init_extensions(app)

    provider = GCSStorageClientProvider(
        project=(
            os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
            or os.getenv("PROJECT_ID", "").strip()
            or os.getenv("GCP_PROJECT", "").strip()
        )
    )
    storage_backend = str(app.config.get("REPORT_STORAGE_BACKEND", "gcs")).strip().lower()
    if storage_backend != "gcs":
        raise ValueError(
            f"Unsupported REPORT_STORAGE_BACKEND '{storage_backend}'. Only 'gcs' is currently configured."
        )

    storage_repository = GCSReportStorageRepository(
        storage_client_provider=provider,
        bucket_name=str(app.config.get("REPORT_STORAGE_BUCKET_NAME", "")).strip(),
        metadata_object_name=str(
            app.config.get("REPORT_STORAGE_METADATA_OBJECT", "reports/report_history.json")
        ).strip(),
        gcs_upload_timeout_seconds=float(
            app.config.get("REPORT_GCS_UPLOAD_TIMEOUT_SECONDS", 300)
        ),
        gcs_upload_retry_deadline_seconds=float(
            app.config.get("REPORT_GCS_UPLOAD_RETRY_DEADLINE_SECONDS", 600)
        ),
    )

    # Shared background manager for asynchronous report generation jobs.
    app.extensions["report_job_manager"] = ReportJobManager(
        storage_client_provider=provider,
        storage_repository=storage_repository,
        reports_prefix=str(app.config.get("REPORT_STORAGE_REPORTS_PREFIX", "reports/generated")).strip(),
        history_limit=int(app.config.get("REPORT_HISTORY_LIMIT", 100)),
        retention_days=int(app.config.get("REPORT_RETENTION_DAYS", 30)),
        trigger_function_url=str(app.config.get("REPORT_TRIGGER_FUNCTION_URL", "")).strip(),
        trigger_timeout_seconds=float(app.config.get("REPORT_TRIGGER_TIMEOUT_SECONDS", 30)),
        trigger_auth_token=str(app.config.get("REPORT_TRIGGER_AUTH_TOKEN", "")).strip(),
        trigger_ca_bundle_path=str(app.config.get("REPORT_TRIGGER_CA_BUNDLE_PATH", "")).strip(),
        trigger_insecure_skip_verify=bool(
            app.config.get("REPORT_TRIGGER_INSECURE_SKIP_VERIFY", False)
        ),
        trigger_disable_system_proxy=bool(
            app.config.get("REPORT_TRIGGER_DISABLE_SYSTEM_PROXY", False)
        ),
        print_key_columns=list(app.config.get("REPORT_PRINT_KEY_COLUMNS", ["pub_name", "state", "caption"])),
        print_date_column=str(app.config.get("REPORT_PRINT_DATE_COLUMN", "finalschdt")).strip(),
        print_kpi_column=app.config.get("REPORT_PRINT_KPI_COLUMN", 0),
        ev_join_mapping=dict(
            app.config.get(
                "REPORT_EV_JOIN_MAPPING",
                {
                    "pub_name": "pub_name",
                    "state": "state",
                    "caption": "caption",
                },
            )
        ),
        ev_date_column=str(app.config.get("REPORT_EV_DATE_COLUMN", "finalschdt")).strip(),
        ev_kpi_column=str(app.config.get("REPORT_EV_KPI_COLUMN", "kpi")).strip(),
        window_before=int(app.config.get("REPORT_WINDOW_BEFORE", 2)),
        window_after=int(app.config.get("REPORT_WINDOW_AFTER", 2)),
    )

    register_blueprints(app)
    register_app_password_gate(app)

    def static_asset(filename: str) -> str:
        """Resolve static asset URL from local static in dev, GCS in prod."""
        cleaned_name = filename.lstrip("/")
        if app.config.get("USE_GCS_STATIC_ASSETS"):
            static_base_url = str(app.config.get("STATIC_ASSET_BASE_URL", "")).strip().rstrip("/")
            if static_base_url:
                return f"{static_base_url}/{cleaned_name}"
        return url_for("static", filename=cleaned_name)

    @app.context_processor
    def inject_template_globals() -> dict[str, object]:
        """Expose shared template globals across pages."""
        return {
            "current_year": datetime.now(IST_TZ).year,
            "static_asset": static_asset,
            "app_password_enabled": bool(str(app.config.get("APP_PASSWORD", "")).strip()),
        }

    return app
