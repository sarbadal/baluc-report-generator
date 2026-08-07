"""Application logging configuration."""

from __future__ import annotations

import logging

from flask import Flask


def configure_logging(app: Flask) -> None:
    """Set up base logging behavior for the app lifecycle."""
    if app.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
