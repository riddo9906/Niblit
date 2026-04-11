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

    # HuggingFace — accepts HF_TOKEN, HUGGINGFACE_TOKEN, or HF_API_KEY (Vercel)
    HF_TOKEN: str = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_API_KEY", "")

    # SerpEx search API (https://serpex.dev)
    SERPEX_API_KEY: str = os.getenv("SERPEX_API_KEY", "")

    # SerpAPI — Google/Bing/Yahoo results (https://serpapi.com)
    # Free tier: 100 searches/month. Set SERPAPI_API_KEY to activate.
    SERPAPI_API_KEY: str = os.getenv("SERPAPI_API_KEY", "")

    # GitHub Code Search API token (PAT with public_repo scope)
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # ── Phase 4 LLM providers ─────────────────────────────────────────────────
    # Primary LLM model — used by llm_adapter, llm_module, hf_adapter, hf_brain
    # unless overridden by provider-specific env vars.
    LLM_MODEL: str = os.getenv("NIBLIT_LLM_MODEL", "")

    # Active LLM provider: "hf" (HuggingFace, default) or "anthropic".
    # Can be switched at runtime with `llm-provider hf|anthropic`.
    LLM_ACTIVE_PROVIDER: str = os.getenv("NIBLIT_LLM_PROVIDER", "hf")

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
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

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

    @classmethod
    def validate(cls) -> None:
        """Print a structured table of which services are enabled/disabled.

        Call this once at boot (e.g. from main.py after creating NiblitCore)
        so operators can immediately see what keys are present without reading
        logs or digging through the .env file.

        Example output::

            ┌─── Niblit service status ─────────────────────────────────────────┐
            │  ✅  HuggingFace LLM         HF_TOKEN              set            │
            │  ❌  OpenAI LLM              OPENAI_API_KEY         not set       │
            └───────────────────────────────────────────────────────────────────┘
        """
        import logging
        _log = logging.getLogger("NiblitConfig")

        checks = [
            ("HuggingFace LLM",      "HF_TOKEN",           bool(cls.HF_TOKEN)),
            ("OpenAI LLM",           "OPENAI_API_KEY",      bool(cls.OPENAI_API_KEY)),
            ("Anthropic LLM",        "ANTHROPIC_API_KEY",   bool(cls.ANTHROPIC_API_KEY)),
            ("Qdrant vector store",  "QDRANT_URL",          bool(cls.QDRANT_URL)),
            ("SerpEx search",        "SERPEX_API_KEY",      bool(cls.SERPEX_API_KEY)),
            ("SerpAPI search",       "SERPAPI_API_KEY",     bool(cls.SERPAPI_API_KEY)),
            ("GitHub code search",   "GITHUB_TOKEN",        bool(cls.GITHUB_TOKEN)),
            ("API key auth",         "NIBLIT_API_KEY",      bool(cls.NIBLIT_API_KEY)),
        ]

        any_llm = bool(cls.HF_TOKEN or cls.OPENAI_API_KEY or cls.ANTHROPIC_API_KEY)

        lines = ["", "┌─── Niblit service status ───────────────────────────────────────┐"]
        for label, env_var, enabled in checks:
            icon  = "✅" if enabled else "❌"
            state = "set" if enabled else "not set"
            lines.append(f"│  {icon}  {label:<24} {env_var:<22} {state:<10}│")
        lines.append("└─────────────────────────────────────────────────────────────────┘")

        for line in lines:
            _log.warning(line)
            print(line)

        if not any_llm:
            msg = (
                "\n"
                "┌──────────────────────────────────────────────────────────────────┐\n"
                "│  ⚠️  NO LLM PROVIDER configured — Niblit will echo inputs only.   │\n"
                "│  Set at least ONE of:                                             │\n"
                "│    HF_TOKEN          (HuggingFace router — free tier available)  │\n"
                "│    OPENAI_API_KEY    (OpenAI — pay-as-you-go)                    │\n"
                "│    ANTHROPIC_API_KEY (Anthropic — pay-as-you-go)                 │\n"
                "└──────────────────────────────────────────────────────────────────┘"
            )
            print(msg)
            _log.warning(msg)


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


if __name__ == "__main__":
    print('Running config.py')
