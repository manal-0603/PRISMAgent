"""Central configuration, loaded from environment variables / the local `.env` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- LLM backbone -------------------------------------------------------
    llm_provider: str = "groq"  # groq | ollama | anthropic | openai
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # Three models. Each has its own rate-limit and daily-token bucket, so spreading the
    # tasks over them is what makes a whole review fit in a free-tier day.
    model_primary: str = "openai/gpt-oss-120b"
    model_secondary: str = "qwen/qwen3.8-27b"
    model_fast: str = "openai/gpt-oss-20b"

    # Which model does which task ("primary" | "secondary" | "fast"). Constraints kept by
    # the defaults: reviewer A != reviewer B (independent dual screening), critic != writer,
    # appraiser != extractor, auditor != both reviewers.
    role_planner: str = "primary"
    role_search: str = "primary"
    role_reviewer_a: str = "fast"
    role_reviewer_b: str = "secondary"
    role_adjudicator: str = "primary"
    role_extractor: str = "primary"
    role_appraiser: str = "fast"
    role_writer: str = "primary"
    role_critic: str = "secondary"
    role_auditor: str = "primary"
    role_utility: str = "fast"

    # Free-tier friendly limits (per model). Raise them on a paid plan.
    tokens_per_minute: int = 8000
    tokens_per_day: int = 200_000  # daily allowance per model; only used to estimate what is left (`sysrev quota`)
    requests_per_minute: int = 30
    max_request_tokens: int = 6000  # prompt + completion budget of a single call
    llm_max_retries: int = 6
    # A rate-limit wait longer than this (seconds) is treated as an exhausted daily quota: the stage
    # stops and the run can be resumed later. Raise it (e.g. 3600) to let an unattended run crawl on
    # as the quota regenerates.
    llm_max_wait_seconds: int = 300

    # --- Embeddings / RAG ---------------------------------------------------
    embedding_provider: str = "fastembed"  # fastembed | ollama
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    ollama_embedding_model: str = "nomic-embed-text"
    reranker_model: str = "ms-marco-MiniLM-L-12-v2"
    chunk_size: int = 1100  # characters
    chunk_overlap: int = 150

    # --- Literature sources (all optional; the pipeline works without them) --
    openalex_api_key: str | None = None
    s2_api_key: str | None = None
    ncbi_api_key: str | None = None
    # Only sent to scholarly APIs (polite pools, Unpaywall) when explicitly set.
    contact_email: str | None = None

    # --- Storage ------------------------------------------------------------
    runs_dir: Path = Path("runs")
    cache_dir: Path = Path(".cache")

    def model_for(self, role: str) -> str:
        return {
            "primary": self.model_primary,
            "secondary": self.model_secondary,
            "fast": self.model_fast,
        }[role]

    def role(self, task: str) -> str:
        """Model role in charge of a task, e.g. role('extractor') -> 'primary'."""
        return getattr(self, f"role_{task}")

    def task_model(self, task: str) -> str:
        return self.model_for(self.role(task))

    def task_models(self) -> dict[str, str]:
        tasks = [name.removeprefix("role_") for name in type(self).model_fields if name.startswith("role_")]
        return {task: self.task_model(task) for task in tasks}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
