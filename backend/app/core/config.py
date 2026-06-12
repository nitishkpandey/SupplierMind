"""
app/core/config.py — All application settings in one place.

USAGE anywhere in the codebase:
    from app.core.config import settings
    print(settings.DATABASE_URL)
    print(settings.GROQ_API_KEY)
"""

import warnings
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Reads environment variables from .env file automatically.
    Pydantic validates types — wrong type = clear error at startup.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown env vars instead of crashing
    )

    # ── Application ──────────────────────────────────────────────────
    APP_ENV: Literal["development", "production"] = "development"
    APP_NAME: str = "SupplierMind"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Database ─────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://suppliermind:suppliermind_dev@localhost:5433/suppliermind"
    )
    POSTGRES_USER: str = "suppliermind"
    POSTGRES_PASSWORD: str = "suppliermind_dev"
    POSTGRES_DB: str = "suppliermind"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433

    # ── LLM ──────────────────────────────────────────────────────────
    # LLM_PROVIDER selects the PRIMARY provider. With "openai", Groq acts as
    # the automatic fallback on retryable failures when GROQ_API_KEY is set
    # (Development Plan, Phase 1).
    LLM_PROVIDER: Literal["groq", "anthropic", "openai"] = "groq"
    LLM_MODEL_NAME: str = "llama-3.1-8b-instant"
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_NAME: str = "gpt-4o-mini"
    GROQ_FALLBACK_MODEL_NAME: str = "llama-3.1-8b-instant"

    # ── Embeddings ───────────────────────────────────────────────────
    EMBEDDING_PROVIDER: Literal["voyage", "openai"] = "voyage"
    VOYAGE_API_KEY: str = ""

    # ── Vector Database ───────────────────────────────────────────────
    VECTOR_DB_PROVIDER: Literal["milvus", "chromadb"] = "milvus"
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    CHROMA_PERSIST_PATH: str = "./chroma_db"

    # ── Redis ─────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Authentication ────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production-use-32-byte-hex"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"

    # ── Geocoding ─────────────────────────────────────────────────────
    NOMINATIM_USER_AGENT: str = "suppliermind-thesis/1.0"

    # ── External APIs ─────────────────────────────────────────────────
    OPENSANCTIONS_API_KEY: str = ""
    SANCTIONS_API_BASE_URL: str = "https://api.opensanctions.org"
    WIKIDATA_SPARQL_ENDPOINT: str = "https://query.wikidata.org/sparql"

    # ── External Discovery ─────────────────────────────────────────────
    TAVILY_API_KEY: str = ""
    OPENCORPORATES_API_KEY: str = ""
    ENABLE_EXTERNAL_DISCOVERY: bool = True
    EXTERNAL_DISCOVERY_MAX_RESULTS: int = 10
    EXTERNAL_DISCOVERY_TIMEOUT: int = 30

    # ── Pipeline tuning ───────────────────────────────────────────────
    EVALUATOR_MAX_RETRIES: int = 1
    SSE_TIMEOUT_SECONDS: int = 300
    SSE_CLEANUP_DELAY_SECONDS: int = 300
    QUERY_MIN_LENGTH: int = 10
    QUERY_MAX_LENGTH: int = 1000

    # ── Mode ──────────────────────────────────────────────────────────
    LITE_MODE: bool = False

    # ── Computed Properties ───────────────────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def effective_vector_db(self) -> str:
        """Return chromadb if LITE_MODE, regardless of VECTOR_DB_PROVIDER."""
        return "chromadb" if self.LITE_MODE else self.VECTOR_DB_PROVIDER

    # ── Validators ────────────────────────────────────────────────────
    @field_validator("SECRET_KEY")
    @classmethod
    def warn_if_default_secret_key(cls, v: str) -> str:
        if v == "change-me-in-production-use-32-byte-hex":
            warnings.warn(
                "SECRET_KEY is using the default value. "
                "Generate a real key: python -c \"import secrets; print(secrets.token_hex(32))\"",
                stacklevel=2,
            )
        return v

    @model_validator(mode="after")
    def require_api_keys_in_production(self) -> "Settings":
        """Crash at startup if critical keys are missing in production."""
        if self.is_production:
            missing = []
            if not self.GROQ_API_KEY:
                missing.append("GROQ_API_KEY")
            if not self.VOYAGE_API_KEY:
                missing.append("VOYAGE_API_KEY")
            if not self.GOOGLE_CLIENT_ID:
                missing.append("GOOGLE_CLIENT_ID")
            if not self.GOOGLE_CLIENT_SECRET:
                missing.append("GOOGLE_CLIENT_SECRET")
            if not self.GITHUB_CLIENT_ID:
                missing.append("GITHUB_CLIENT_ID")
            if not self.GITHUB_CLIENT_SECRET:
                missing.append("GITHUB_CLIENT_SECRET")
            if self.SECRET_KEY == "change-me-in-production-use-32-byte-hex":
                missing.append("SECRET_KEY")
            if missing:
                raise ValueError(
                    f"Missing required production environment variables: {', '.join(missing)}"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a CACHED Settings instance.
    @lru_cache means this function only runs ONCE — the .env file
    is read once at startup, not on every request.

    Use as FastAPI dependency:
        def route(settings: Settings = Depends(get_settings)): ...
    """
    return Settings()


# Module-level singleton for direct imports
# Usage: from app.core.config import settings
settings = get_settings()