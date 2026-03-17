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

    # SerpEx search API (https://serpex.dev)
    SERPEX_API_KEY: str = os.getenv("SERPEX_API_KEY", "")

    # GitHub Code Search API token (PAT with public_repo scope)
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # ── Phase 4 LLM providers ─────────────────────────────────────────────────
    # OpenAI (https://platform.openai.com/api-keys)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Anthropic (https://console.anthropic.com/account/keys)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

    # ── Phase 4 Research APIs ────────────────────────────────────────────────
    # Stack Exchange / Stack Overflow API
    # Register at https://stackapps.com/apps/oauth/register
    STACKOVERFLOW_API_KEY: str = os.getenv("STACKOVERFLOW_API_KEY", "")

    # PyPI simple index (no key required; base URL configurable for mirrors)
    PYPI_API_URL: str = os.getenv("PYPI_API_URL", "https://pypi.org/pypi")

    # ── Searchcode ────────────────────────────────────────────────────────────
    # searchcode.com public code-search API (no authentication required).
    # SEARCHCODE_MCP_URL: the official MCP endpoint; configure it in any
    # MCP client with:  claude mcp add searchcode --transport http <url>
    SEARCHCODE_API_URL: str = os.getenv("SEARCHCODE_API_URL", "https://searchcode.com/api")
    SEARCHCODE_MCP_URL: str = os.getenv("SEARCHCODE_MCP_URL", "https://api.searchcode.com/v1/mcp")

    # ── Phase 3 Knowledge / Vector Database ──────────────────────────────────
    # Qdrant vector store (https://cloud.qdrant.io)
    QDRANT_URL: str = os.getenv("QDRANT_URL", "")
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "niblit_knowledge")

    # Embedding model for vector store (local sentence-transformers model name
    # or HF repo ID; used when Qdrant is enabled)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # ── Phase 5 Sandbox Execution ─────────────────────────────────────────────
    # Docker socket / host — set to empty string to disable sandboxed execution
    DOCKER_HOST: str = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    SANDBOX_ENABLED: bool = os.getenv("SANDBOX_ENABLED", "False").lower() in ("1", "true", "yes")
    SANDBOX_IMAGE: str = os.getenv("SANDBOX_IMAGE", "python:3.12-slim")
    SANDBOX_TIMEOUT: int = int(os.getenv("SANDBOX_TIMEOUT", "30"))
    SANDBOX_MEMORY_MB: int = int(os.getenv("SANDBOX_MEMORY_MB", "256"))

    # ── NewsAPI ───────────────────────────────────────────────────────────────
    # NewsAPI.org API key for top-headlines aggregation in the upgrade pipeline.
    # Register at https://newsapi.org/register (free tier available).
    NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")

    # ── Neo4j Graph Database ─────────────────────────────────────────────────
    # Connection details for Neo4j (optional — pipeline falls back to SQLite).
    # Cloud: https://neo4j.com/cloud/aura-free/  |  Self-host: docker run neo4j
    NEO4J_URI: str = os.getenv("NEO4J_URI", "")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASS: str = os.getenv("NEO4J_PASS", "")

    # ── Prometheus / Grafana Metrics ─────────────────────────────────────────
    # Set PROMETHEUS_ENABLED=true to start a /metrics HTTP endpoint.
    # Requires: pip install prometheus-client
    PROMETHEUS_ENABLED: bool = os.getenv("PROMETHEUS_ENABLED", "False").lower() in ("1", "true", "yes")
    PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "9090"))

    # API security
    NIBLIT_API_KEY: str = os.getenv("NIBLIT_API_KEY", "")

    # ── MCP (Model Context Protocol) ─────────────────────────────────────────
    # Set MCP_ENABLED=true to activate the /mcp and /mcp/sse endpoints and
    # the stdio transport (``python -m modules.mcp_server``).
    MCP_ENABLED: bool = os.getenv("MCP_ENABLED", "true").lower() in ("1", "true", "yes")
    # Bearer token that MCP clients must supply in the Authorization header.
    # Leave blank to disable auth on the MCP endpoint (not recommended in production).
    MCP_SECRET: str = os.getenv("MCP_SECRET", "")
    # Host/port for the optional standalone HTTP MCP server.
    MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
    MCP_PORT: int = int(os.getenv("MCP_PORT", "8765"))

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
