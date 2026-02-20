"""
config/settings.py
==================
Central configuration for the Autonomous CI/CD Healing Intelligence Core.
All values are environment-driven — no hardcoded paths or secrets.
Supports: OpenAI GPT-4o  OR  Google Gemini (free tier) — configurable via LLM_PROVIDER.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Production-grade settings via environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM Provider ──────────────────────────────────────────────────────────
    # Set LLM_PROVIDER=gemini to use Google Gemini (FREE)
    # Set LLM_PROVIDER=openai to use OpenAI GPT-4o (paid)
    LLM_PROVIDER: str = Field(default="groq", description="'groq', 'gemini', or 'openai'")

    # ── OpenAI ────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = Field(default=None)
    OPENAI_MODEL: str = Field(default="gpt-4o")

    # ── Google Gemini (FREE) ──────────────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = Field(default=None)
    GEMINI_MODEL: str = Field(default="gemini-pro")

    # ── Groq (FREE — Llama 3.3 70B, 500 tok/sec) ─────────────────────────────
    GROQ_API_KEY: Optional[str] = Field(default=None)
    GROQ_MODEL: str = Field(default="llama-3.1-8b-instant")

    # ── Shared LLM settings ───────────────────────────────────────────────────
    OPENAI_TEMPERATURE_START: float = Field(default=0.2, ge=0.0, le=1.0)
    OPENAI_TEMPERATURE_MIN: float = Field(default=0.05, ge=0.0, le=1.0)

    # ── GitHub ────────────────────────────────────────────────────────────────
    GITHUB_TOKEN: Optional[str] = Field(default=None)
    GITHUB_COMMIT_PREFIX: str = Field(default="[AI-AGENT]")
    GITHUB_TARGET_BRANCH: str = Field(default="ai-healing")

    # ── Orchestration ─────────────────────────────────────────────────────────
    MAX_RETRIES: int = Field(default=5, ge=1, le=10)
    SANDBOX_TIMEOUT_SECONDS: int = Field(default=120, ge=30, le=600)
    PATCH_MAX_LINES: int = Field(default=50)

    # ── Sandbox ───────────────────────────────────────────────────────────────
    SANDBOX_DOCKER_IMAGE: str = Field(default="python:3.11-slim")
    SANDBOX_MEMORY_LIMIT: str = Field(default="512m")
    SANDBOX_CPU_QUOTA: int = Field(default=50000)

    # ── Paths ─────────────────────────────────────────────────────────────────
    RESULTS_DIR: Path = Field(default=Path("backend/results"))
    WORKSPACE_DIR: Path = Field(default=Path("/tmp/cicd_workspace"))

    # ── Scoring ───────────────────────────────────────────────────────────────
    SCORE_BASE: float = Field(default=100.0)
    SCORE_PER_FIX: float = Field(default=10.0)
    SCORE_SPEED_FACTOR: float = Field(default=0.5)
    SCORE_REGRESSION_PENALTY: float = Field(default=25.0)

    # ── Determinism ───────────────────────────────────────────────────────────
    RANDOM_SEED: int = Field(default=42)

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def active_model(self) -> str:
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_MODEL
        if self.LLM_PROVIDER == "gemini":
            return self.GEMINI_MODEL
        return self.OPENAI_MODEL

    @property
    def active_api_key(self) -> str:
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_API_KEY or ""
        if self.LLM_PROVIDER == "gemini":
            return self.GEMINI_API_KEY or ""
        return self.OPENAI_API_KEY or ""

    @property
    def results_dir_abs(self) -> Path:
        return Path(os.getcwd()) / self.RESULTS_DIR

    @property
    def workspace_dir_abs(self) -> Path:
        p = self.WORKSPACE_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p


# Singleton
settings = Settings()
