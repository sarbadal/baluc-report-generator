"""Runtime entry point for the Flask application."""

from __future__ import annotations

import os

from app import create_app

app = create_app()


def entry_point():
    """Return the Flask app instance for external runners."""
    return app


if __name__ == "__main__":
    app.run(debug=True, port=5001)

