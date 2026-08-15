from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    model: str
    normalization_runs: int
    demo_access_code: str
    openai_calls_enabled: bool
    max_normalization_jobs_per_day: int
    max_global_api_calls_per_day: int
    max_output_tokens: int
    vector_store_id: str
    rag_max_results: int


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def get_settings() -> Settings:
    runs = int(os.getenv("NORMALIZATION_RUNS", "3"))
    if runs < 1 or runs % 2 == 0:
        raise ValueError("NORMALIZATION_RUNS must be a positive odd number")
    max_jobs = int(os.getenv("MAX_NORMALIZATION_JOBS_PER_DAY", "10"))
    max_calls = int(os.getenv("MAX_GLOBAL_API_CALLS_PER_DAY", "100"))
    max_output_tokens = int(os.getenv("MAX_OUTPUT_TOKENS", "500"))
    rag_max_results = int(os.getenv("RAG_MAX_RESULTS", "5"))
    if min(max_jobs, max_calls, max_output_tokens, rag_max_results) < 1:
        raise ValueError("Usage limits must be positive integers")
    return Settings(
        db_path=Path(os.getenv("ITRA_DB_PATH", "data/itra.db")),
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
        normalization_runs=runs,
        demo_access_code=os.getenv("DEMO_ACCESS_CODE", ""),
        openai_calls_enabled=_bool_env("OPENAI_CALLS_ENABLED"),
        max_normalization_jobs_per_day=max_jobs,
        max_global_api_calls_per_day=max_calls,
        max_output_tokens=max_output_tokens,
        vector_store_id=os.getenv("OPENAI_VECTOR_STORE_ID", "").strip(),
        rag_max_results=rag_max_results,
    )
