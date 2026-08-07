"""Extension registry and initialization hooks.

Add third-party Flask extensions here (database, migrations, auth, cache, etc.)
and initialize them from ``init_extensions``.
"""

from flask import Flask


# Example placeholders for future extension instances:
# db = SQLAlchemy()
# migrate = Migrate()
# login_manager = LoginManager()


def init_extensions(app: Flask) -> None:
    """Initialize Flask extensions on the app instance."""
    # Future extension initialization example:
    # db.init_app(app)
    # migrate.init_app(app, db)
    _ = app
