from pathlib import Path

from itra_normalizer.db import (
    connect,
    control_catalog_rows,
    ingest_fixtures,
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
        "sites": 2,
        "controls": 32,
        "assessments": 64,
        "partial": 5,
        "not_applicable": 2,
        "normalized": 0,
        "review_findings": 0,
    }


def test_dashboard_breakdowns_cover_every_assessment(tmp_path: Path) -> None:
    connection = loaded_database(tmp_path)
    assert sum(row["count"] for row in status_by_section(connection)) == 64
    catalog = control_catalog_rows(connection)
    assert len(catalog) == 32
    assert all(row["site_count"] == 2 for row in catalog)
