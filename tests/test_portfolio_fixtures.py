import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_full_portfolio_has_consistent_control_coverage() -> None:
    catalog = load(ROOT / "data/control_catalog.json")
    expected_ids = [row["control_id"] for row in catalog]
    fixtures = [load(path) for path in sorted((ROOT / "data/parsed").glob("SYN-*.json"))]
    assert len(fixtures) == 10
    assert [fixture["site_id"] for fixture in fixtures] == [f"SYN-{index:03d}" for index in range(1, 11)]
    assert all([control["control_id"] for control in fixture["controls"]] == expected_ids for fixture in fixtures)
    assert all(len(fixture["controls"]) == 32 for fixture in fixtures)


def test_generated_fixtures_retain_ground_truth_traceability() -> None:
    ground_truth = load(ROOT / "data/portfolio_ground_truth.json")
    truth_by_id = {site["itra_id"]: site for site in ground_truth["sites"]}
    for index in range(1, 9):
        fixture = load(ROOT / f"data/parsed/SYN-{index:03d}.json")
        truth = truth_by_id[fixture["site_id"]]
        assert fixture["ground_truth_normalized"] == truth["normalized"]
        assert fixture["ground_truth_evidence"] == truth["evidence"]


def test_calibration_split_keeps_outlier_in_validation() -> None:
    fixtures = [load(path) for path in sorted((ROOT / "data/parsed").glob("SYN-*.json"))]
    cohorts = {
        fixture["site_id"]: fixture.get(
            "portfolio_cohort",
            "Calibration" if fixture["site_id"] == "SYN-009" else "Validation",
        )
        for fixture in fixtures
    }
    assert sum(value == "Calibration" for value in cohorts.values()) == 5
    assert sum(value == "Validation" for value in cohorts.values()) == 5
    assert cohorts["SYN-008"] == "Validation"
