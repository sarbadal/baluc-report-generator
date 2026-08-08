"""Central configuration module for all environments."""

from __future__ import annotations

import os


GCS_FILE_DISCOVERY_RULES: dict[str, dict[str, str]] = {
    "EV": {
        "folder": "ev",
        "filename_pattern": r"^ev_dump_(\d{8})\.csv$",
    },
    "PRINT": {
        "folder": "print",
        "filename_pattern": r"^print_dump(\d{8})\.csv$",
    },
    "CONTACT": {
        "folder": "contact",
        "filename_pattern": r"^contact_dump_(\d{8})\.csv$",
    },
}


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
