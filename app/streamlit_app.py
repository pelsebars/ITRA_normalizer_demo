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


st.set_page_config(page_title="ITRA Normalizer", page_icon="🛡️", layout="wide")
settings = get_settings()
connection = connect(settings.db_path)
ingest_fixtures(connection, ROOT / "data/parsed", ROOT / "data/control_catalog.json")
usage = usage_today(connection)

st.title("ITRA Normalizer")
st.caption("Demo environment · Synthetic data only · AC.2.1 vertical slice")

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
        st.warning("OpenAI kill switch is OFF. The demo is read-only.")
    if not os.getenv("OPENAI_API_KEY"):
        st.warning("OPENAI_API_KEY is not configured.")

    st.subheader("Today's safeguards")
    st.metric(
        "Normalization jobs",
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

st.subheader("Evidence and reconciliation")
for row in rows:
    badge = row["status_reconciled"] or "Not normalized"
    with st.expander(f"{row['site_name']} · {badge}", expanded=True):
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
