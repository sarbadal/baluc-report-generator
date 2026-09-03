"""Blueprint registration module.

Group feature blueprints in this package and register them centrally here.
"""

from flask import Flask

from app.blueprints.auth import auth_blueprint
from app.blueprints.home import home_blueprint


def register_blueprints(app: Flask) -> None:
    """Register all HTTP blueprints with the application."""
    blueprints = [
        auth_blueprint,
        home_blueprint,
    ]

    for blueprint in blueprints:
        app.register_blueprint(blueprint)
