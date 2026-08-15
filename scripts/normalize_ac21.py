#!/usr/bin/env python3
from itra_normalizer.config import get_settings
from itra_normalizer.db import connect, ingest_fixtures
from itra_normalizer.normalization import normalize_ac21, openai_classifier


def main() -> None:
    settings = get_settings()
    connection = connect(settings.db_path)
    ingest_fixtures(connection)
    summary = normalize_ac21(
        connection,
        classifier=openai_classifier(settings.model, settings.max_output_tokens),
        model=settings.model,
        runs=settings.normalization_runs,
        calls_enabled=settings.openai_calls_enabled,
        max_jobs_per_day=settings.max_normalization_jobs_per_day,
        max_api_calls_per_day=settings.max_global_api_calls_per_day,
    )
    print(
        f"Normalized {summary.processed_sites} sites; reused {summary.cached_sites} cached sites; "
        f"used {summary.api_calls} API calls and {summary.total_tokens} tokens."
    )


if __name__ == "__main__":
    main()
