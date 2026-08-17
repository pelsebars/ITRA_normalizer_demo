from pathlib import Path

from itra_normalizer.db import connect, ingest_fixtures, portfolio_sites


def test_ingest_loads_all_fixture_records(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    assert ingest_fixtures(connection) == 10
    assert connection.execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 10
    assert connection.execute("SELECT COUNT(*) FROM control_catalog").fetchone()[0] == 32
    assert connection.execute("SELECT COUNT(*) FROM control_answers").fetchone()[0] == 320
    assert connection.execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 24
    sites = portfolio_sites(connection)
    assert sum(row["portfolio_cohort"] == "Calibration" for row in sites) == 5
    assert sum(row["portfolio_cohort"] == "Validation" for row in sites) == 5
    assert all(row["control_count"] == 32 for row in sites)


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    ingest_fixtures(connection)
    assert connection.execute("SELECT COUNT(*) FROM control_answers").fetchone()[0] == 320
