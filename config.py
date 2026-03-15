"""
config.py — Centralized configuration management for Niblit.

Reads environment variables with sensible defaults for development,
testing, and production modes.  Import `settings` for a ready-to-use
configuration object.

Usage::

    from config import settings
    print(settings.PORT)
"""

import os


class Config:
    """Base configuration – reads environment variables."""

    # Flask / server
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
    TESTING: bool = os.getenv("TESTING", "False").lower() in ("1", "true", "yes")
    PORT: int = int(os.getenv("PORT", "5000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "niblit-secret-change-me")

    # HuggingFace
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")

    # API security
    NIBLIT_API_KEY: str = os.getenv("NIBLIT_API_KEY", "")

    # Rate limiting
    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "10"))
    RATE_WINDOW: int = int(os.getenv("RATE_WINDOW", "60"))

    # Database
    DB_PATH: str = os.getenv("NIBLIT_DB_PATH", "niblit.db")
    SQLITE_DB_PATH: str = os.getenv("NIBLIT_SQLITE_DB_PATH", "niblit_data.sqlite")

    # Mobile
    MOBILE_ENABLED: bool = os.getenv("MOBILE_ENABLED", "True").lower() in ("1", "true", "yes")
    # Comma-separated list of allowed CORS origins; "*" allows all.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # Feature toggles
    ENABLE_DASHBOARD: bool = os.getenv("ENABLE_DASHBOARD", "True").lower() in ("1", "true", "yes")
    ENABLE_MEMORY_API: bool = os.getenv("ENABLE_MEMORY_API", "True").lower() in ("1", "true", "yes")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")  # "json" or "text"


class DevelopmentConfig(Config):
    """Development overrides."""

    DEBUG = True


class TestingConfig(Config):
    """Testing overrides."""

    TESTING = True
    DEBUG = True
    DB_PATH = ":memory:"
    SQLITE_DB_PATH = ":memory:"
    HF_TOKEN = "test-token"
    NIBLIT_API_KEY = ""


class ProductionConfig(Config):
    """Production overrides."""

    DEBUG = False
    TESTING = False


# ---------------------------------------------------------------------------
# Active configuration object
# ---------------------------------------------------------------------------
_env = os.getenv("FLASK_ENV", "development").lower()

if _env == "production":
    settings = ProductionConfig()
elif _env == "testing":
    settings = TestingConfig()
else:
    settings = DevelopmentConfig()
