from __future__ import annotations

import hmac
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from itra_normalizer.config import get_settings
from itra_normalizer.db import connect, control_rows, ingest_fixtures
from itra_normalizer.normalization import (
    NormalizationBlocked,
    normalize_ac21,
    openai_classifier,
    usage_today,
)
from itra_normalizer.rag import ask_evidence


st.set_page_config(page_title="ITRA Normalizer", page_icon="🛡️", layout="wide")
settings = get_settings()
connection = connect(settings.db_path)
ingest_fixtures(connection, ROOT / "data/parsed", ROOT / "data/control_catalog.json")
usage = usage_today(connection)

st.title("ITRA Normalizer")
st.caption("Demo environment · Synthetic data only · AC.2.1 normalized across two ITRAs")

if "api_authorized" not in st.session_state:
    st.session_state.api_authorized = False

with st.sidebar:
    st.header("Pipeline")
    st.success("2 golden fixtures loaded")
    st.code(settings.model, language=None)

    st.subheader("API access")
    if not settings.demo_access_code:
        st.error("Paid actions are locked: DEMO_ACCESS_CODE is not configured.")
    elif not st.session_state.api_authorized:
        access_code = st.text_input("Demo access code", type="password")
        if st.button("Unlock paid actions", width="stretch"):
            st.session_state.api_authorized = hmac.compare_digest(
                access_code, settings.demo_access_code
            )
            if st.session_state.api_authorized:
                st.rerun()
            st.error("Invalid access code.")
    else:
        st.success("Paid actions unlocked for this browser session")
        if st.button("Lock", width="stretch"):
            st.session_state.api_authorized = False
            st.rerun()

    if not settings.openai_calls_enabled:
        st.warning("OpenAI calls are disabled by the kill switch. The demo is read-only.")
    if not os.getenv("OPENAI_API_KEY"):
        st.warning("OPENAI_API_KEY is not configured.")

    st.subheader("Today's safeguards")
    st.metric(
        "Paid actions",
        f"{usage['jobs']} / {settings.max_normalization_jobs_per_day}",
    )
    st.metric(
        "OpenAI API calls",
        f"{usage['api_calls']} used · {usage['reserved_api_calls']} reserved / "
        f"{settings.max_global_api_calls_per_day}",
    )
    st.caption(f"Tokens recorded today: {usage['total_tokens']:,}")

    paid_actions_ready = (
        st.session_state.api_authorized
        and settings.openai_calls_enabled
        and bool(os.getenv("OPENAI_API_KEY"))
        and bool(settings.demo_access_code)
    )
    if st.button(
        "Run or reuse AC.2.1 normalization",
        type="primary",
        width="stretch",
        disabled=not paid_actions_ready,
    ):
        try:
            with st.spinner(f"Assessing each site {settings.normalization_runs} times…"):
                summary = normalize_ac21(
                    connection,
                    classifier=openai_classifier(settings.model, settings.max_output_tokens),
                    model=settings.model,
                    runs=settings.normalization_runs,
                    calls_enabled=settings.openai_calls_enabled,
                    max_jobs_per_day=settings.max_normalization_jobs_per_day,
                    max_api_calls_per_day=settings.max_global_api_calls_per_day,
                )
            if summary.api_calls:
                st.success(
                    f"Normalized {summary.processed_sites} sites with {summary.api_calls} API calls "
                    f"and {summary.total_tokens:,} tokens."
                )
            else:
                st.info(f"Reused cached results for {summary.cached_sites} sites. No API calls made.")
            st.rerun()
        except NormalizationBlocked as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(f"Normalization failed safely: {exc}")

rows = control_rows(connection, "AC.2.1")
if not rows:
    st.error("No AC.2.1 fixture data found.")
    st.stop()

st.subheader("Why this control matters")
st.info(
    "Both sites report Compliant and answer No/No – routine users in S.7. "
    "Only the detailed control evidence reveals whether a shared engineering login exists."
)
st.caption(
    "Scope: this vertical slice normalizes AC.2.1 across both ITRAs. Other controls are loaded "
    "as source data but are not yet normalized."
)

summary_rows = []
for row in rows:
    normalized = json.loads(row["normalized_value_json"]) if row["normalized_value_json"] else {}
    summary_rows.append({
        "Site": row["site_name"],
        "Raw status": row["status_raw"],
        "S.7 answer": row["security_answer"],
        "Shared accounts": normalized.get("shared_accounts_used", "Not normalized"),
        "Reconciliation": row["status_reconciled"] or "Not normalized",
        "Confidence": row["confidence"],
        "Agreement": row["llm_agreement_rate"] or "—",
        "QA review": "Yes" if row["needs_review"] else ("No" if row["needs_review"] is not None else "—"),
    })
st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")

review_rows = [row for row in rows if row["needs_review"]]
if review_rows:
    st.warning(
        f"QA review required for {len(review_rows)} of {len(rows)} sites. "
        "A reconciliation finding or disagreement between repeated model runs triggered review."
    )

st.subheader("Evidence and reconciliation")
for row in rows:
    badge = row["status_reconciled"] or "Not normalized"
    with st.expander(f"{row['site_name']} · {badge}", expanded=True):
        if row["needs_review"]:
            st.warning(
                f"QA review required · model agreement {row['llm_agreement_rate'] or 'not available'}"
            )
        left, right = st.columns(2)
        with left:
            st.markdown("**Raw evidence**")
            st.markdown(f"**Status:** {row['status_raw']}")
            st.markdown(f"**S.7:** {row['security_answer']}")
            st.write(row["detailed_description"])
        with right:
            st.markdown("**Normalized assessment**")
            if row["normalized_value_json"]:
                st.json(json.loads(row["normalized_value_json"]))
                st.write(row["reconciliation_note"])
                st.caption(
                    f"Model {row['model_version']} · Prompt {row['prompt_version']} · "
                    f"Agreement {row['llm_agreement_rate']}"
                )
            else:
                st.warning("Unlock and run normalization to generate this assessment.")

st.divider()
st.subheader("Ask the source evidence")
st.caption(
    "Managed retrieval over the two synthetic ITRA PDFs. Answers are generated from retrieved "
    "document evidence and show the cited source files."
)

rag_ready = paid_actions_ready and bool(settings.vector_store_id)
if not settings.vector_store_id:
    st.info("RAG is not configured yet. Set OPENAI_VECTOR_STORE_ID after indexing the PDFs.")

with st.form("rag_question_form"):
    question = st.text_input(
        "Question",
        placeholder="Which site describes shared interactive accounts, and what is the exception?",
        max_chars=1000,
        disabled=not rag_ready,
    )
    ask_clicked = st.form_submit_button(
        "Ask evidence",
        disabled=not rag_ready,
        type="primary",
    )

if ask_clicked:
    try:
        with st.spinner("Searching the ITRA evidence…"):
            answer = ask_evidence(
                connection,
                question,
                model=settings.model,
                vector_store_id=settings.vector_store_id,
                max_results=settings.rag_max_results,
                max_output_tokens=settings.max_output_tokens,
                calls_enabled=settings.openai_calls_enabled,
                max_jobs_per_day=settings.max_normalization_jobs_per_day,
                max_api_calls_per_day=settings.max_global_api_calls_per_day,
            )
        st.markdown(answer.text)
        if answer.citations:
            st.caption("Sources: " + " · ".join(citation.filename for citation in answer.citations))
        else:
            st.warning("The response contained no file citation. Treat it as unverified.")
        st.caption(f"Response {answer.response_id} · {answer.total_tokens:,} tokens")
    except (NormalizationBlocked, ValueError) as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error(f"Evidence query failed safely: {exc}")
