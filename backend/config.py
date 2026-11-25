"""
Application Configuration
-------------------------
Loads configuration settings from environment variables or a .env file.
Provides centralized defaults for the AI Compliance Inspection Agent.
"""

from typing import Literal
import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("COMPLIANCE_DATA_DIR", BASE_DIR / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
DECISIONS_DIR = DATA_DIR / "decisions"
MOCK_RULES_PATH = BASE_DIR / "backend" / "db" / "mock_rules.json"

# Ensure data directories exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DECISIONS_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Application settings with type-hinted defaults."""
    
    # Provider & Model Settings
    LLM_PROVIDER: str = "mock"
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    LLM_MODEL_ID: str = "gpt-4o-mini"
    PROMPT_VERSION: str = "v1.0"
    
    # Resilience Settings (Configurable Timeouts & Retries)
    LLM_TIMEOUT_SECONDS: int = 90
    LLM_MAX_RETRIES: int = 2
    LLM_REQUESTS_PER_MINUTE: int = 4
    LLM_RATE_LIMIT_SAFETY_BUFFER: float = 2.0
    
    RULE_RETRIEVAL_MODE: Literal["full", "keyword"] = "full"
    INSPECTION_CONTEXT_CHARS: int = Field(default=800, ge=0, le=4000)

    # Chunking Settings
    CHUNK_MIN_CHARS: int = 40
    CHUNK_MAX_CHARS: int = 2000
    
    # Server Settings
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = True
    INSPECTION_WORKERS: int = Field(default=1, ge=1, le=8)
    WORKER_SHUTDOWN_SECONDS: float = Field(default=5, ge=0, le=60)

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Global settings singleton
settings = Settings()

