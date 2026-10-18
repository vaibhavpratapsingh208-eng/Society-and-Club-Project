"""Application package and backwards-compatible Flask entry point.

The existing feature implementation remains loadable while the application is
being migrated into blueprints. ``create_app`` is the entry point for Flask
and tests, and the re-exported objects keep existing imports working.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from .config import Config
from .extensions import csrf, db, login_manager, migrate
from . import models

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_PATH = _PROJECT_ROOT / "app.py"
_SPEC = spec_from_file_location("_club_legacy_app", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load application module from {_LEGACY_PATH}")
_legacy = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_legacy)

app = _legacy.app
get_db = _legacy.get_db
init_db = _legacy.init_db
app.config.from_object(Config)

if db is not None:
    db.init_app(app)
if migrate is not None:
    migrate.init_app(app, db)
if login_manager is not None:
    login_manager.init_app(app)
    login_manager.login_view = "login"

    class LegacyUser:
        def __init__(self, member):
            self.id = member["id"]
            self.name = member["name"]
            self.email = member["email"]
            self.role = member["role"]

        def get_id(self):
            return str(self.id)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            member = get_db().execute(
                "SELECT id,name,email,role FROM members WHERE id=? AND status='Active'",
                (int(user_id),),
            ).fetchone()
        except (TypeError, ValueError):
            return None
        return LegacyUser(member) if member else None

# Keep the legacy form/API routes compatible. New blueprints can opt into
# CSRF protection without making existing demo clients send a token.
if csrf is not None and app.config.get("WTF_CSRF_ENABLED"):
    csrf.init_app(app)
    csrf.exempt(_legacy.app)

from .blueprints.auth.routes import bp as auth_blueprint
from .blueprints.company.routes import bp as company_blueprint
from .blueprints.societies.routes import bp as societies_blueprint
from .blueprints.members.routes import bp as members_blueprint
from .blueprints.elections.routes import bp as elections_blueprint

for blueprint in (
    auth_blueprint,
    company_blueprint,
    societies_blueprint,
    members_blueprint,
    elections_blueprint,
):
    app.register_blueprint(blueprint)


def create_app(test_config=None):
    """Return the configured Flask application.

    The legacy routes are deliberately retained during the migration so
    existing URLs and SQLite data continue to work. New modules can register
    blueprints here without changing the Flask CLI command.
    """

    if test_config:
        app.config.update(test_config)
    return app


__all__ = ["app", "create_app", "get_db", "init_db"]
