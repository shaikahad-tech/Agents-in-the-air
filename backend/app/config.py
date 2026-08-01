"""Centralized configuration via Pydantic Settings.

All deployment knobs — ports, paths, rate limits, security keys — live here.
Reads from environment variables (with sensible defaults) so the app is
12-factor compliant and works unchanged across local, Docker, and Render.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_prefix="AITA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Agents-in-the-air"
    app_version: str = "0.2.0"
    env: str = Field(default="development")  # development | staging | production
    log_level: str = "INFO"

    # --- Paths ---
    data_dir: Path = Path("/tmp/aita/data")
    workspace_dir: Path = Path("/tmp/aita/workspace")

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- CORS ---
    # Comma-separated list of allowed origins, or * for all (not recommended for prod)
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # --- Auth ---
    # If set, all /api/* endpoints require this key in the X-API-Key header.
    # If empty, auth is disabled (dev mode only).
    api_key: str = ""

    # --- Rate limiting ---
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100  # requests per window
    rate_limit_window: int = 60  # seconds

    # --- Executor ---
    max_concurrent_nodes: int = 10  # max parallel nodes per workflow run
    default_node_timeout: float = 120.0  # seconds; per-node deadline
    max_workflow_nodes: int = 500  # safety cap on workflow size
    max_code_output_bytes: int = 1_000_000  # 1 MB cap on code-node result

    # --- HTTP node ---
    http_max_redirects: int = 5
    http_default_timeout: float = 30.0
    # Block requests to private / internal IPs (SSRF protection)
    http_block_private_ips: bool = True
    # Optional allowlist of permitted host patterns (glob), e.g. ["api.openai.com"]
    http_allowed_hosts: list[str] = Field(default_factory=list)

    # --- Code node sandbox ---
    code_sandbox_enabled: bool = True
    code_max_cpu_seconds: int = 30

    @field_validator("env")
    @classmethod
    def _check_env(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("development", "staging", "production"):
            raise ValueError(f"env must be development|staging|production, got '{v}'")
        return v

    def ensure_dirs(self) -> None:
        """Create data + workspace directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    s = Settings()
    s.ensure_dirs()
    return s
