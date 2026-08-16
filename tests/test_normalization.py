import json
from pathlib import Path

from itra_normalizer.db import connect, ingest_fixtures
import pytest

from itra_normalizer.normalization import (
    AC21Assessment,
    ClassificationResult,
    ControlAssessment,
    NormalizationBlocked,
    normalize_ac21,
    normalize_section,
    usage_today,
)


def expected_classifier(evidence: dict) -> AC21Assessment:
    if evidence["site_id"] == "SYN-009":
        return AC21Assessment(
            shared_accounts_used="Yes - justified exception",
            compensating_control_present=True,
            status_reconciled="Partially divergent",
            reconciliation_note="A common engineering login is used as an exception despite the unqualified Compliant status.",
            confidence=0.9,
            needs_review=True,
        )
    return AC21Assessment(
        shared_accounts_used="No",
        compensating_control_present=None,
        status_reconciled="Aligned",
        reconciliation_note="No shared human interactive account is described.",
        confidence=0.96,
        needs_review=False,
    )


def test_ac21_hero_case_is_persisted(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    summary = normalize_ac21(connection, expected_classifier, "test-model", runs=3)
    assert summary.processed_sites == 2
    assert summary.api_calls == 6
    rows = connection.execute(
        "SELECT * FROM control_answers WHERE control_id='AC.2.1' ORDER BY site_id"
    ).fetchall()
    indigo, juniper = rows
    assert json.loads(indigo["normalized_value_json"])["shared_accounts_used"] == "Yes - justified exception"
    assert indigo["status_reconciled"] == "Partially divergent"
    assert indigo["needs_review"] == 1
    assert indigo["llm_agreement_rate"] == "3/3"
    assert json.loads(juniper["normalized_value_json"])["shared_accounts_used"] == "No"
    assert juniper["status_reconciled"] == "Aligned"
    assert juniper["needs_review"] == 0


def test_identical_input_reuses_cache_without_calls(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    normalize_ac21(connection, expected_classifier, "test-model", runs=3)

    def must_not_run(_: dict) -> AC21Assessment:
        raise AssertionError("classifier should not be called for cached input")

    summary = normalize_ac21(connection, must_not_run, "test-model", runs=3)
    assert summary.processed_sites == 0
    assert summary.cached_sites == 2
    assert summary.api_calls == 0


def test_kill_switch_blocks_before_classifier(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    with pytest.raises(NormalizationBlocked, match="kill switch"):
        normalize_ac21(
            connection, expected_classifier, "test-model", calls_enabled=False
        )
    assert connection.execute("SELECT COUNT(*) FROM normalization_jobs").fetchone()[0] == 0


def test_daily_call_limit_reserves_full_job_before_calls(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    with pytest.raises(NormalizationBlocked, match="daily OpenAI API call limit"):
        normalize_ac21(
            connection, expected_classifier, "test-model", runs=3,
            max_api_calls_per_day=5,
        )
    assert connection.execute("SELECT COUNT(*) FROM normalization_jobs").fetchone()[0] == 0


def test_usage_tokens_are_recorded(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)

    def metered_classifier(evidence: dict) -> ClassificationResult:
        return ClassificationResult(
            assessment=expected_classifier(evidence),
            response_id="resp_test",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

    summary = normalize_ac21(connection, metered_classifier, "test-model", runs=3)
    assert summary.total_tokens == 90
    assert usage_today(connection) == {
        "jobs": 1,
        "api_calls": 6,
        "reserved_api_calls": 6,
        "input_tokens": 60,
        "output_tokens": 30,
        "total_tokens": 90,
    }


def generic_classifier(evidence: dict) -> ControlAssessment:
    partial = evidence["status_raw"] == "Partially Compliant"
    return ControlAssessment(
        evidence_assessment="Partially effective" if partial else "Effective",
        status_reconciled="Aligned",
        evidence_summary=f"Evidence assessed for {evidence['control_id']}.",
        gap_or_qualification="A documented qualification exists." if partial else None,
        confidence=0.9,
        needs_review=partial,
    )


def test_access_control_section_normalizes_all_non_hero_assessments(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    normalize_ac21(connection, expected_classifier, "test-model", runs=3)

    summary = normalize_section(connection, generic_classifier, "test-model", "AC", runs=3)
    assert summary.processed_sites == 20
    assert summary.cached_sites == 2
    assert summary.api_calls == 60
    assert connection.execute(
        """SELECT COUNT(*) FROM control_answers ca
           JOIN control_catalog cc ON cc.control_id=ca.control_id
           WHERE cc.section_prefix='AC' AND ca.normalized_value_json IS NOT NULL"""
    ).fetchone()[0] == 22


def test_access_control_section_reuses_generic_cache(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    normalize_section(connection, generic_classifier, "test-model", "AC", runs=1)

    def must_not_run(_: dict) -> ControlAssessment:
        raise AssertionError("classifier should not run for cached section")

    summary = normalize_section(connection, must_not_run, "test-model", "AC", runs=1)
    assert summary.processed_sites == 0
    assert summary.cached_sites == 22
    assert summary.api_calls == 0


def test_section_job_reserves_full_call_count(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    with pytest.raises(NormalizationBlocked, match="daily OpenAI API call limit"):
        normalize_section(
            connection, generic_classifier, "test-model", "AC", runs=3,
            max_api_calls_per_day=65,
        )
