from pathlib import Path

from itra_normalizer.db import connect, ingest_fixtures


def test_ingest_loads_all_fixture_records(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    assert ingest_fixtures(connection) == 2
    assert connection.execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM control_catalog").fetchone()[0] == 32
    assert connection.execute("SELECT COUNT(*) FROM control_answers").fetchone()[0] == 64
    assert connection.execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 24


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    ingest_fixtures(connection)
    assert connection.execute("SELECT COUNT(*) FROM control_answers").fetchone()[0] == 64
