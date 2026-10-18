"""Shared extension instances used by the modular application."""

try:
    from flask_login import LoginManager
    from flask_migrate import Migrate
    from flask_sqlalchemy import SQLAlchemy
    from flask_wtf import CSRFProtect
except ImportError:  # Optional until the SQLAlchemy migration is enabled.
    LoginManager = Migrate = SQLAlchemy = CSRFProtect = None


db = SQLAlchemy() if SQLAlchemy else None
migrate = Migrate() if Migrate else None
login_manager = LoginManager() if LoginManager else None
csrf = CSRFProtect() if CSRFProtect else None
