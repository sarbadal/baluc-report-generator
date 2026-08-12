"""Central configuration module for all environments."""

from __future__ import annotations

import json
import os


GCS_FILE_DISCOVERY_RULES: dict[str, dict[str, str]] = {
    "EV": {
        "folder": "ev",
        "filename_pattern": r"^ev_fact_(\d{8})\.csv$",
    },
    "PRINT": {
        "folder": "print",
        "filename_pattern": r"^print_fact_(\d{8})\.csv$",
    },
    "CONTACT": {
        "folder": "contact",
        "filename_pattern": r"^contact_fact_(\d{8})\.csv$",
    },
}


def _parse_join_mapping(raw_value: str, default: dict[str, str]) -> dict[str, str]:
    """Parse comma-separated ``print:ev`` mapping string into a dictionary."""
    normalized = raw_value.strip()
    if not normalized:
        return dict(default)

    mapping: dict[str, str] = {}
    for pair in normalized.split(","):
        item = pair.strip()
        if not item or ":" not in item:
            continue
        print_column, ev_column = item.split(":", maxsplit=1)
        left = print_column.strip()
        right = ev_column.strip()
        if left and right:
            mapping[left] = right

    return mapping or dict(default)


def _parse_join_mapping_json(raw_value: str, default: dict[str, str]) -> dict[str, str]:
    """Parse JSON object mapping of ``print_column -> ev_column``."""
    normalized = raw_value.strip()
    if not normalized:
        return dict(default)

    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        return dict(default)

    if not isinstance(parsed, dict):
        return dict(default)

    mapping: dict[str, str] = {}
    for key, value in parsed.items():
        left = str(key).strip()
        right = str(value).strip()
        if left and right:
            mapping[left] = right

    return mapping or dict(default)


class BaseConfig:
    """Base configuration shared by all environments."""

    TESTING = False
    DEBUG = False
    REPORT_GCS_BUCKET_PREFIX = (
        os.getenv("REPORT_GCS_BUCKET_PREFIX")
        or os.getenv("REPORT_STORAGE_BUCKET_NAME")
        or os.getenv("TEST_GCS_BUCKET_NAME")
        or "baluc"
    )
    REPORT_STORAGE_BACKEND = os.getenv("REPORT_STORAGE_BACKEND", "gcs")
    REPORT_STORAGE_BUCKET_NAME = (
        os.getenv("REPORT_STORAGE_BUCKET_NAME")
        or os.getenv("TEST_GCS_BUCKET_NAME")
        or "baluc"
    )
    REPORT_STORAGE_METADATA_OBJECT = os.getenv(
        "REPORT_STORAGE_METADATA_OBJECT",
        "reports/report_history.json",
    )
    REPORT_STORAGE_REPORTS_PREFIX = os.getenv(
        "REPORT_STORAGE_REPORTS_PREFIX",
        "reports/generated",
    )
    REPORT_HISTORY_LIMIT = int(os.getenv("REPORT_HISTORY_LIMIT", "100"))
    REPORT_RETENTION_DAYS = int(os.getenv("REPORT_RETENTION_DAYS", "30"))
    REPORT_STATUS_POLL_SECONDS = int(os.getenv("REPORT_STATUS_POLL_SECONDS", "5"))
    REPORT_GCS_UPLOAD_TIMEOUT_SECONDS = float(os.getenv("REPORT_GCS_UPLOAD_TIMEOUT_SECONDS", "300"))
    REPORT_GCS_UPLOAD_RETRY_DEADLINE_SECONDS = float(
        os.getenv("REPORT_GCS_UPLOAD_RETRY_DEADLINE_SECONDS", "600")
    )
    REPORT_PRINT_KEY_COLUMNS = [
        column.strip()
        for column in os.getenv("REPORT_PRINT_KEY_COLUMNS", "pub_name,state,caption").split(",")
        if column.strip()
    ]
    REPORT_PRINT_DATE_COLUMN = os.getenv("REPORT_PRINT_DATE_COLUMN", "finalschdt").strip()
    _report_print_kpi_column = os.getenv("REPORT_PRINT_KPI_COLUMN", "").strip()
    REPORT_PRINT_KPI_COLUMN: str | int | float = _report_print_kpi_column if _report_print_kpi_column else 0

    _default_ev_join_mapping = {
        "pub_name": "pub_name",
        "state": "state",
        "caption": "ppl",
        "finalschdt": "event_date",
    }
    _ev_join_mapping_from_json = _parse_join_mapping_json(
        os.getenv("REPORT_EV_JOIN_MAPPING_JSON", ""),
        _default_ev_join_mapping,
    )
    _ev_join_mapping_from_legacy = _parse_join_mapping(
        os.getenv("REPORT_EV_JOIN_MAPPING", ""),
        _default_ev_join_mapping,
    )
    REPORT_EV_JOIN_MAPPING = (
        _ev_join_mapping_from_json
        if os.getenv("REPORT_EV_JOIN_MAPPING_JSON", "").strip()
        else _ev_join_mapping_from_legacy
    )
    REPORT_EV_DATE_COLUMN = os.getenv("REPORT_EV_DATE_COLUMN", "event_date").strip()
    REPORT_EV_KPI_COLUMN = os.getenv("REPORT_EV_KPI_COLUMN", "gf_opportunity_created").strip()
    REPORT_WINDOW_BEFORE = int(os.getenv("REPORT_WINDOW_BEFORE", "2"))
    REPORT_WINDOW_AFTER = int(os.getenv("REPORT_WINDOW_AFTER", "2"))

    ENV_TYPE = "dev"
    STATIC_BUCKET = os.getenv("STATIC_BUCKET", "").strip()
    STATIC_GCS_PREFIX = os.getenv("STATIC_GCS_PREFIX", "static").strip().strip("/")
    STATIC_ASSET_BASE_URL = os.getenv("STATIC_ASSET_BASE_URL", "").strip().rstrip("/")
    USE_GCS_STATIC_ASSETS = False

    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        SECRET_KEY = "change-me-in-production"


class DevelopmentConfig(BaseConfig):
    """Configuration tuned for local development."""

    DEBUG = True
    ENV_TYPE = "dev"


class TestingConfig(BaseConfig):
    """Configuration tuned for automated test runs."""

    TESTING = True


class ProductionConfig(BaseConfig):
    """Configuration tuned for production deployments."""

    DEBUG = False
    ENV_TYPE = "prod"
    USE_GCS_STATIC_ASSETS = True
    _explicit_static_asset_base_url = os.getenv("STATIC_ASSET_BASE_URL", "").strip().rstrip("/")
    _static_bucket = os.getenv("STATIC_BUCKET", "").strip()
    _static_prefix = os.getenv("STATIC_GCS_PREFIX", "static").strip().strip("/")
    if _explicit_static_asset_base_url:
        STATIC_ASSET_BASE_URL = _explicit_static_asset_base_url
    elif _static_bucket:
        STATIC_ASSET_BASE_URL = f"https://storage.googleapis.com/{_static_bucket}/{_static_prefix}"


CONFIG_MAP: dict[str, type[BaseConfig]] = {
    "dev": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "prod": ProductionConfig,
    "production": ProductionConfig,
}


def get_config() -> type[BaseConfig]:
    """Resolve which configuration class should be used."""
    env = os.getenv("APP_ENV", "development").strip().lower()
    return CONFIG_MAP.get(env, DevelopmentConfig)
