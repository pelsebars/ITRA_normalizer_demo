from pathlib import Path
from types import SimpleNamespace

import pytest

from itra_normalizer.db import connect, ingest_fixtures
from itra_normalizer.normalization import NormalizationBlocked, usage_today
from itra_normalizer.rag import ask_evidence


class FakeResponse:
    id = "resp_rag_test"
    output_text = "Site Indigo describes a shared engineering login."
    usage = SimpleNamespace(input_tokens=20, output_tokens=10, total_tokens=30)

    def model_dump(self) -> dict:
        return {
            "output": [
                {
                    "type": "file_search_call",
                    "results": [
                        {
                            "filename": "SYN_ITRA_009_Site_Indigo.pdf",
                            "file_id": "file_indigo",
                            "score": 0.91,
                            "text": "During troubleshooting, a common engineering login is used.",
                        }
                    ],
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [
                                {
                                    "type": "file_citation",
                                    "filename": "SYN_ITRA_009_Site_Indigo.pdf",
                                    "file_id": "file_indigo",
                                },
                                {
                                    "type": "file_citation",
                                    "filename": "SYN_ITRA_009_Site_Indigo.pdf",
                                    "file_id": "file_indigo",
                                },
                            ],
                        }
                    ],
                }
            ]
        }


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeResponse()


def test_rag_query_uses_file_search_and_records_usage(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)

    answer = ask_evidence(
        connection,
        "Which site uses a shared login?",
        model="test-model",
        vector_store_id="vs_test",
        client=client,
    )

    assert answer.text.startswith("Site Indigo")
    assert [citation.filename for citation in answer.citations] == [
        "SYN_ITRA_009_Site_Indigo.pdf"
    ]
    assert len(answer.evidence) == 1
    assert answer.evidence[0].score == 0.91
    assert answer.evidence[0].text.startswith("During troubleshooting")
    assert responses.kwargs["tools"] == [
        {
            "type": "file_search",
            "vector_store_ids": ["vs_test"],
            "max_num_results": 5,
        }
    ]
    assert responses.kwargs["include"] == ["file_search_call.results"]
    assert responses.kwargs["store"] is False
    assert "temperature" not in responses.kwargs
    assert tuple(connection.execute(
        "SELECT action, status FROM normalization_jobs"
    ).fetchone()) == ("rag_query", "completed")
    assert usage_today(connection)["api_calls"] == 1
    assert usage_today(connection)["total_tokens"] == 30


def test_rag_kill_switch_blocks_before_reservation(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    ingest_fixtures(connection)
    with pytest.raises(NormalizationBlocked, match="kill switch"):
        ask_evidence(
            connection,
            "Question",
            model="test-model",
            vector_store_id="vs_test",
            calls_enabled=False,
        )
    assert connection.execute("SELECT COUNT(*) FROM normalization_jobs").fetchone()[0] == 0
