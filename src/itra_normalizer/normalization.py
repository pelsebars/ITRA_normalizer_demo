from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Optional, Union

from pydantic import BaseModel, Field

from .db import control_rows


PROMPT_VERSION = "ac-2-1-v1"


class NormalizationBlocked(RuntimeError):
    """Raised when a server-side cost or concurrency guard blocks a job."""


class AC21Assessment(BaseModel):
    shared_accounts_used: Literal["No", "Yes", "Yes - justified exception"]
    compensating_control_present: Optional[bool]
    status_reconciled: Literal["Aligned", "Partially divergent", "Divergent"]
    reconciliation_note: str = Field(description="A concise, evidence-based explanation in English.")
    confidence: float = Field(ge=0, le=1)
    needs_review: bool


@dataclass(frozen=True)
class ClassificationResult:
    assessment: AC21Assessment
    response_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class NormalizationSummary:
    processed_sites: int
    cached_sites: int
    api_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


ClassifierOutput = Union[AC21Assessment, ClassificationResult]
Classifier = Callable[[dict], ClassifierOutput]


SYSTEM_PROMPT = """You are a cautious IT risk assessment reviewer.
Assess control AC.2.1 using the raw control status, detailed description, and the related S.7 answer.

Rubric:
- 'No': no shared human interactive account is described.
- 'Yes': shared human interactive accounts are used without a clearly justified exception.
- 'Yes - justified exception': a shared human interactive account is used as an explicit exception. Do not infer that an exception is justified merely because the assessor called the control compliant.
- 'Aligned': raw status fully reflects the described practice.
- 'Partially divergent': raw status is broadly defensible but hides a material exception or qualification that QA should review.
- 'Divergent': raw status conflicts with the described practice.

Treat service identities used only for automation as different from shared interactive human accounts.
Use only the supplied evidence. If evidence is incomplete, lower confidence and require review.
"""


def openai_classifier(model: str, max_output_tokens: int = 500) -> Classifier:
    from openai import OpenAI

    client = OpenAI()

    def classify(evidence: dict) -> ClassificationResult:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, indent=2)},
            ],
            text_format=AC21Assessment,
            temperature=0,
            max_output_tokens=max_output_tokens,
            store=False,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model did not return a parsed assessment")
        usage = response.usage
        return ClassificationResult(
            assessment=response.output_parsed,
            response_id=response.id,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )

    return classify


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_day_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _evidence(row: sqlite3.Row) -> dict:
    return {
        "site_id": row["site_id"],
        "site_name": row["site_name"],
        "control_id": row["control_id"],
        "control_text": row["control_text"],
        "status_raw": row["status_raw"],
        "detailed_description": row["detailed_description"],
        "implementation_considerations": row["implementation_considerations"],
        "security_question_id": "S.7",
        "security_answer": row["security_answer"],
        "security_comment": row["security_comment"],
    }


def _input_hash(evidence: dict, model: str, runs: int) -> str:
    payload = {
        "evidence": evidence,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "runs": runs,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _vote_key(result: AC21Assessment) -> tuple:
    return (
        result.shared_accounts_used,
        result.compensating_control_present,
        result.status_reconciled,
        result.needs_review,
    )


def choose_consensus(results: list[AC21Assessment]) -> tuple[AC21Assessment, str]:
    if not results:
        raise ValueError("At least one result is required")
    counts = Counter(_vote_key(result) for result in results)
    winner_key, winner_count = counts.most_common(1)[0]
    winner = next(result for result in results if _vote_key(result) == winner_key)
    if winner_count != len(results):
        winner = winner.model_copy(update={"needs_review": True})
    return winner, f"{winner_count}/{len(results)}"


def usage_today(connection: sqlite3.Connection) -> dict[str, int]:
    row = connection.execute(
        """SELECT COUNT(*) AS jobs,
                  COALESCE(SUM(actual_api_calls), 0) AS api_calls,
                  COALESCE(SUM(planned_api_calls), 0) AS reserved_api_calls,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens
           FROM normalization_jobs WHERE started_at >= ?""",
        (_utc_day_start(),),
    ).fetchone()
    return dict(row)


def _reserve_job(
    connection: sqlite3.Connection,
    input_hash: str,
    model: str,
    planned_calls: int,
    max_jobs_per_day: int,
    max_api_calls_per_day: int,
) -> int:
    try:
        connection.execute("BEGIN IMMEDIATE")
        stale_before = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        connection.execute(
            """UPDATE normalization_jobs
               SET status='failed', finished_at=?, error='Recovered stale running job.'
               WHERE status='running' AND started_at < ?""",
            (_utc_now(), stale_before),
        )
        active = connection.execute(
            "SELECT COUNT(*) FROM normalization_jobs WHERE status='running'"
        ).fetchone()[0]
        if active:
            raise NormalizationBlocked("Another normalization job is already running.")
        totals = connection.execute(
            """SELECT COUNT(*) AS jobs,
                      COALESCE(SUM(planned_api_calls), 0) AS calls
               FROM normalization_jobs WHERE started_at >= ?""",
            (_utc_day_start(),),
        ).fetchone()
        if totals["jobs"] >= max_jobs_per_day:
            raise NormalizationBlocked("The daily normalization job limit has been reached.")
        if totals["calls"] + planned_calls > max_api_calls_per_day:
            raise NormalizationBlocked("This job would exceed the daily OpenAI API call limit.")
        cursor = connection.execute(
            """INSERT INTO normalization_jobs(
                 action, input_hash, model, prompt_version, started_at, status, planned_api_calls
               ) VALUES ('normalize_ac21', ?, ?, ?, ?, 'running', ?)""",
            (input_hash, model, PROMPT_VERSION, _utc_now(), planned_calls),
        )
        connection.commit()
        return int(cursor.lastrowid)
    except Exception:
        connection.rollback()
        raise


def _record_call(connection: sqlite3.Connection, job_id: int, model: str, result: ClassificationResult) -> None:
    connection.execute(
        """INSERT INTO api_usage_events(
             job_id, occurred_at, action, model, response_id,
             input_tokens, output_tokens, total_tokens, status
           ) VALUES (?, ?, 'normalize_ac21', ?, ?, ?, ?, ?, 'completed')""",
        (job_id, _utc_now(), model, result.response_id, result.input_tokens,
         result.output_tokens, result.total_tokens),
    )
    connection.execute(
        """UPDATE normalization_jobs SET
             actual_api_calls=actual_api_calls+1,
             input_tokens=input_tokens+?, output_tokens=output_tokens+?, total_tokens=total_tokens+?
           WHERE job_id=?""",
        (result.input_tokens, result.output_tokens, result.total_tokens, job_id),
    )
    connection.commit()


def _finish_job(connection: sqlite3.Connection, job_id: int, status: str, error: str = "") -> None:
    connection.execute(
        "UPDATE normalization_jobs SET status=?, finished_at=?, error=? WHERE job_id=?",
        (status, _utc_now(), error[:1000] or None, job_id),
    )
    connection.commit()


def normalize_ac21(
    connection: sqlite3.Connection,
    classifier: Classifier,
    model: str,
    runs: int = 3,
    *,
    calls_enabled: bool = True,
    max_jobs_per_day: int = 10,
    max_api_calls_per_day: int = 100,
    force: bool = False,
) -> NormalizationSummary:
    if not calls_enabled:
        raise NormalizationBlocked("OpenAI calls are disabled by the server kill switch.")
    if runs < 1 or runs % 2 == 0:
        raise ValueError("runs must be a positive odd number")
    rows = control_rows(connection, "AC.2.1")
    work = []
    for row in rows:
        evidence = _evidence(row)
        fingerprint = _input_hash(evidence, model, runs)
        cached = not force and row["normalized_value_json"] and row["normalized_input_hash"] == fingerprint
        if not cached:
            work.append((row, evidence, fingerprint))
    cached_sites = len(rows) - len(work)
    if not work:
        return NormalizationSummary(0, cached_sites, 0, 0, 0, 0)

    batch_hash = hashlib.sha256("".join(item[2] for item in work).encode()).hexdigest()
    job_id = _reserve_job(
        connection, batch_hash, model, len(work) * runs,
        max_jobs_per_day, max_api_calls_per_day,
    )
    usage = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    try:
        for row, evidence, fingerprint in work:
            assessments = []
            for _ in range(runs):
                raw_result = classifier(evidence)
                result = raw_result if isinstance(raw_result, ClassificationResult) else ClassificationResult(raw_result)
                assessments.append(result.assessment)
                _record_call(connection, job_id, model, result)
                usage["api_calls"] += 1
                usage["input_tokens"] += result.input_tokens
                usage["output_tokens"] += result.output_tokens
                usage["total_tokens"] += result.total_tokens
            assessment, agreement = choose_consensus(assessments)
            normalized_value = {
                "shared_accounts_used": assessment.shared_accounts_used,
                "compensating_control_present": assessment.compensating_control_present,
            }
            connection.execute(
                """UPDATE control_answers SET
                     normalized_value_json=?, status_reconciled=?, reconciliation_note=?,
                     confidence=?, needs_review=?, llm_agreement_rate=?, model_version=?,
                     prompt_version=?, normalized_input_hash=?, normalized_at=?
                   WHERE site_id=? AND control_id='AC.2.1'""",
                (json.dumps(normalized_value), assessment.status_reconciled,
                 assessment.reconciliation_note, assessment.confidence, int(assessment.needs_review),
                 agreement, model, PROMPT_VERSION, fingerprint, _utc_now(), row["site_id"]),
            )
            connection.commit()
        _finish_job(connection, job_id, "completed")
    except Exception as exc:
        _finish_job(connection, job_id, "failed", str(exc))
        raise
    return NormalizationSummary(len(work), cached_sites, **usage)
