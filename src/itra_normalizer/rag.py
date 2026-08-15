from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .normalization import (
    NormalizationBlocked,
    finish_api_job,
    record_api_usage,
    reserve_api_job,
)


RAG_PROMPT_VERSION = "itra-evidence-rag-v1"


@dataclass(frozen=True)
class Citation:
    filename: str
    file_id: str


@dataclass(frozen=True)
class EvidenceSnippet:
    filename: str
    file_id: str
    score: float | None
    text: str


@dataclass(frozen=True)
class RagAnswer:
    text: str
    citations: tuple[Citation, ...]
    evidence: tuple[EvidenceSnippet, ...]
    response_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


def _citations(response: Any) -> tuple[Citation, ...]:
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    found: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            for annotation in content.get("annotations", []):
                if annotation.get("type") != "file_citation":
                    continue
                key = (annotation.get("filename", "Unknown file"), annotation.get("file_id", ""))
                if key not in seen:
                    seen.add(key)
                    found.append(Citation(filename=key[0], file_id=key[1]))
    return tuple(found)


def _evidence_snippets(response: Any) -> tuple[EvidenceSnippet, ...]:
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    snippets: list[EvidenceSnippet] = []
    for item in payload.get("output", []):
        if item.get("type") != "file_search_call":
            continue
        for result in item.get("results") or []:
            text = " ".join((result.get("text") or "").split())
            if not text:
                continue
            snippets.append(
                EvidenceSnippet(
                    filename=result.get("filename") or "Unknown file",
                    file_id=result.get("file_id") or "",
                    score=result.get("score"),
                    text=text,
                )
            )
    return tuple(snippets)


def ask_evidence(
    connection: sqlite3.Connection,
    question: str,
    *,
    model: str,
    vector_store_id: str,
    max_results: int = 5,
    max_output_tokens: int = 500,
    calls_enabled: bool = True,
    max_jobs_per_day: int = 10,
    max_api_calls_per_day: int = 100,
    client: Any = None,
) -> RagAnswer:
    question = question.strip()
    if not calls_enabled:
        raise NormalizationBlocked("OpenAI calls are disabled by the server kill switch.")
    if not vector_store_id:
        raise NormalizationBlocked("The ITRA evidence vector store is not configured.")
    if not question:
        raise ValueError("A question is required")
    if len(question) > 1000:
        raise ValueError("Question must be 1,000 characters or fewer")

    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "question": question,
                "model": model,
                "vector_store_id": vector_store_id,
                "prompt_version": RAG_PROMPT_VERSION,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    job_id = reserve_api_job(
        connection,
        fingerprint,
        model,
        1,
        max_jobs_per_day,
        max_api_calls_per_day,
        action="rag_query",
        prompt_version=RAG_PROMPT_VERSION,
    )
    try:
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        response = client.responses.create(
            model=model,
            instructions=(
                "Answer only from the indexed synthetic ITRA evidence. Distinguish raw self-reported "
                "status from practices described in free text. If the evidence is insufficient, say so. "
                "Keep the answer concise and ensure factual claims are supported by file citations."
            ),
            input=question,
            tools=[
                {
                    "type": "file_search",
                    "vector_store_ids": [vector_store_id],
                    "max_num_results": max_results,
                }
            ],
            include=["file_search_call.results"],
            max_output_tokens=max_output_tokens,
            store=False,
        )
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0
        record_api_usage(
            connection,
            job_id,
            model,
            action="rag_query",
            response_id=response.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        answer = RagAnswer(
            text=response.output_text,
            citations=_citations(response),
            evidence=_evidence_snippets(response),
            response_id=response.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        finish_api_job(connection, job_id, "completed")
        return answer
    except Exception as exc:
        finish_api_job(connection, job_id, "failed", str(exc))
        raise
