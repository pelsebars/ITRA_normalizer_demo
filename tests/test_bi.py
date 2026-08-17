from pathlib import Path

from itra_normalizer.db import (
    connect,
    control_catalog_rows,
    ingest_fixtures,
    normalization_progress_by_section,
    portfolio_summary,
    status_by_section,
)


def loaded_database(tmp_path: Path):
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    return connection


def test_portfolio_summary(tmp_path: Path) -> None:
    summary = portfolio_summary(loaded_database(tmp_path))
    assert dict(summary) == {
        "sites": 10,
        "controls": 32,
        "assessments": 320,
        "partial": 32,
        "not_compliant": 2,
        "not_applicable": 17,
        "normalized": 0,
        "review_findings": 0,
    }


def test_dashboard_breakdowns_cover_every_assessment(tmp_path: Path) -> None:
    connection = loaded_database(tmp_path)
    assert sum(row["count"] for row in status_by_section(connection)) == 320
    catalog = control_catalog_rows(connection)
    assert len(catalog) == 32
    assert all(row["site_count"] == 10 for row in catalog)


def test_normalization_progress_covers_all_domains(tmp_path: Path) -> None:
    progress = normalization_progress_by_section(loaded_database(tmp_path))
    assert len(progress) == 8
    assert sum(row["total"] for row in progress) == 320
    assert sum(row["normalized"] for row in progress) == 0
    assert sum(row["remaining"] for row in progress) == 320
