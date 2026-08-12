"""Application logging configuration."""

from __future__ import annotations

import logging

from flask import Flask


def configure_logging(app: Flask) -> None:
    """Set up base logging behavior for the app lifecycle."""
    log_level = logging.DEBUG if app.debug else logging.INFO
    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    # force=True ensures Cloud Functions runtime handlers are aligned with app settings.
    logging.basicConfig(level=log_level, format=log_format, force=True)
