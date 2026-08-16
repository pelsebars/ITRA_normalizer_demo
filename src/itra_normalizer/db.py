from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(control_answers)").fetchall()
    }
    if "normalized_input_hash" not in columns:
        connection.execute("ALTER TABLE control_answers ADD COLUMN normalized_input_hash TEXT")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def ingest_fixtures(
    connection: sqlite3.Connection,
    parsed_dir: Path | str = "data/parsed",
    catalog_path: Path | str = "data/control_catalog.json",
) -> int:
    initialize(connection)
    catalog = _load_json(Path(catalog_path))
    connection.executemany(
        """INSERT INTO control_catalog(control_id, section_prefix, control_text)
           VALUES (:control_id, :section_prefix, :control_text)
           ON CONFLICT(control_id) DO UPDATE SET
             section_prefix=excluded.section_prefix,
             control_text=excluded.control_text""",
        catalog,
    )

    site_count = 0
    for fixture_path in sorted(Path(parsed_dir).glob("*.json")):
        payload = _load_json(fixture_path)
        _ingest_site(connection, payload)
        site_count += 1
    connection.commit()
    return site_count


def _ingest_site(connection: sqlite3.Connection, site: dict[str, Any]) -> None:
    connection.execute(
        """INSERT INTO sites(site_id, site_name, business_application, application_id, state)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(site_id) DO UPDATE SET
             site_name=excluded.site_name,
             business_application=excluded.business_application,
             application_id=excluded.application_id,
             state=excluded.state""",
        (
            site["site_id"], site["site_name"], site.get("business_application"),
            site.get("application_id"), site.get("state"),
        ),
    )
    for control in site["controls"]:
        connection.execute(
            """INSERT INTO control_answers(
                 site_id, control_id, status_raw, type, detailed_description,
                 implementation_considerations
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(site_id, control_id) DO UPDATE SET
                 status_raw=excluded.status_raw,
                 type=excluded.type,
                 detailed_description=excluded.detailed_description,
                 implementation_considerations=excluded.implementation_considerations""",
            (
                site["site_id"], control["control_id"], control["status_raw"],
                control.get("type"), control["detailed_description"],
                control.get("implementation_considerations"),
            ),
        )
    _upsert_answers(connection, "scoping_answers", site["site_id"], site.get("scoping_answers", []), "rationale")
    _upsert_answers(connection, "technical_answers", site["site_id"], site.get("technical_answers", []), "comment")
    _upsert_answers(connection, "security_answers", site["site_id"], site.get("security_answers", []), "comment")
    for risk in site.get("risks", []):
        connection.execute(
            """INSERT INTO risks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(site_id, risk_id) DO UPDATE SET
                 name=excluded.name, gross_impact=excluded.gross_impact,
                 gross_likelihood=excluded.gross_likelihood, gross_risk=excluded.gross_risk,
                 net_impact=excluded.net_impact, net_likelihood=excluded.net_likelihood,
                 net_risk=excluded.net_risk, comments=excluded.comments""",
            (site["site_id"], risk["risk_id"], risk.get("name"), risk.get("gross_impact"),
             risk.get("gross_likelihood"), risk.get("gross_risk"), risk.get("net_impact"),
             risk.get("net_likelihood"), risk.get("net_risk"), risk.get("comments")),
        )


def _upsert_answers(
    connection: sqlite3.Connection,
    table: str,
    site_id: str,
    answers: Iterable[dict[str, Any]],
    text_field: str,
) -> None:
    if table not in {"scoping_answers", "technical_answers", "security_answers"}:
        raise ValueError("Unsupported answer table")
    for answer in answers:
        connection.execute(
            f"""INSERT INTO {table}(site_id, question_id, question, answer, {text_field})
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(site_id, question_id) DO UPDATE SET
                  question=excluded.question, answer=excluded.answer,
                  {text_field}=excluded.{text_field}""",
            (site_id, answer["question_id"], answer.get("question"), answer.get("answer"), answer.get(text_field)),
        )


def control_rows(connection: sqlite3.Connection, control_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT ca.*, s.site_name, cc.control_text,
                  sa.answer AS security_answer, sa.comment AS security_comment
           FROM control_answers ca
           JOIN sites s ON s.site_id = ca.site_id
           JOIN control_catalog cc ON cc.control_id = ca.control_id
           LEFT JOIN security_answers sa
             ON sa.site_id = ca.site_id AND sa.question_id = 'S.7'
           WHERE ca.control_id = ?
           ORDER BY ca.site_id""",
        (control_id,),
    ).fetchall()


def portfolio_summary(connection: sqlite3.Connection) -> sqlite3.Row:
    return connection.execute(
        """SELECT
             (SELECT COUNT(*) FROM sites) AS sites,
             (SELECT COUNT(*) FROM control_catalog) AS controls,
             (SELECT COUNT(*) FROM control_answers) AS assessments,
             (SELECT COUNT(*) FROM control_answers
               WHERE status_raw = 'Partially Compliant') AS partial,
             (SELECT COUNT(*) FROM control_answers
               WHERE status_raw = 'Not Applicable') AS not_applicable,
             (SELECT COUNT(*) FROM control_answers
               WHERE normalized_value_json IS NOT NULL) AS normalized,
             (SELECT COUNT(*) FROM control_answers
               WHERE needs_review = 1) AS review_findings"""
    ).fetchone()


def status_by_section(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT cc.section_prefix AS section, ca.status_raw AS status, COUNT(*) AS count
           FROM control_answers ca
           JOIN control_catalog cc ON cc.control_id = ca.control_id
           GROUP BY cc.section_prefix, ca.status_raw
           ORDER BY cc.section_prefix, ca.status_raw"""
    ).fetchall()


def control_catalog_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT cc.control_id, cc.section_prefix, cc.control_text,
                  COUNT(ca.site_id) AS site_count,
                  SUM(CASE WHEN ca.status_raw = 'Compliant' THEN 1 ELSE 0 END) AS compliant,
                  SUM(CASE WHEN ca.status_raw = 'Partially Compliant' THEN 1 ELSE 0 END) AS partial,
                  SUM(CASE WHEN ca.status_raw = 'Not Applicable' THEN 1 ELSE 0 END) AS not_applicable,
                  SUM(CASE WHEN ca.needs_review = 1 THEN 1 ELSE 0 END) AS review_findings
           FROM control_catalog cc
           LEFT JOIN control_answers ca ON ca.control_id = cc.control_id
           GROUP BY cc.control_id, cc.section_prefix, cc.control_text
           ORDER BY cc.control_id"""
    ).fetchall()


def section_control_rows(
    connection: sqlite3.Connection,
    section_prefix: str,
    *,
    exclude_control_ids: Iterable[str] = (),
) -> list[sqlite3.Row]:
    excluded = tuple(exclude_control_ids)
    placeholders = ",".join("?" for _ in excluded)
    exclusion = f"AND ca.control_id NOT IN ({placeholders})" if excluded else ""
    return connection.execute(
        f"""SELECT ca.*, s.site_name, cc.control_text, cc.section_prefix,
                   (SELECT json_group_object(question_id, answer)
                      FROM security_answers sa WHERE sa.site_id = ca.site_id) AS security_context_json
            FROM control_answers ca
            JOIN sites s ON s.site_id = ca.site_id
            JOIN control_catalog cc ON cc.control_id = ca.control_id
            WHERE cc.section_prefix = ? {exclusion}
            ORDER BY ca.control_id, ca.site_id""",
        (section_prefix, *excluded),
    ).fetchall()
