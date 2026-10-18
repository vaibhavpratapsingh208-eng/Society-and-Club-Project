"""Environment-based configuration for the club portal."""

import os

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "development-only-change-me")
    DATABASE_FILE = os.environ.get("DATABASE_FILE", "club.db")
    DATABASE_URL = os.environ.get("DATABASE_URL")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or f"sqlite:///{os.path.join(BASE_DIR, DATABASE_FILE)}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = os.environ.get("WTF_CSRF_ENABLED", "false").lower() == "true"
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "").strip()


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
