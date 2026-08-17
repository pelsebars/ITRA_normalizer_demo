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
from itra_normalizer.db import (
    connect, control_catalog_rows, control_rows, ingest_fixtures,
    normalization_progress_by_section, portfolio_summary, status_by_section,
)
from itra_normalizer.normalization import (
    NormalizationBlocked, normalize_section, openai_control_classifier, usage_today,
)
from itra_normalizer.rag import ask_evidence

st.set_page_config(page_title="ITRA Normalizer", page_icon="🛡️", layout="wide")
settings = get_settings()
connection = connect(settings.db_path)
ingest_fixtures(connection, ROOT / "data/parsed", ROOT / "data/control_catalog.json")
usage = usage_today(connection)
domain_progress = [dict(row) for row in normalization_progress_by_section(connection)]
DOMAIN_NAMES = {
    "AC": "Access Control", "BC": "Business Continuity", "DI": "Data Integrity",
    "LG": "Logging", "NW": "Network Security", "PD": "Physical & Device",
    "TP": "Third Party", "VM": "Vulnerability Management",
}

st.title("ITRA Normalizer")
st.caption("Portfolio intelligence from inconsistent assessments · Synthetic demo data")

if "api_authorized" not in st.session_state:
    st.session_state.api_authorized = False

with st.sidebar:
    st.header("Demo controls")
    st.success("10 synthetic assessments loaded")
    st.caption(f"Model: {settings.model}")
    st.subheader("Paid API access")
    if not settings.demo_access_code:
        st.error("Paid actions are locked: DEMO_ACCESS_CODE is not configured.")
    elif not st.session_state.api_authorized:
        access_code = st.text_input("Demo access code", type="password")
        if st.button("Unlock paid actions", width="stretch"):
            st.session_state.api_authorized = hmac.compare_digest(access_code, settings.demo_access_code)
            if st.session_state.api_authorized:
                st.rerun()
            st.error("Invalid access code.")
    else:
        st.success("Paid actions unlocked for this browser session")
        if st.button("Lock", width="stretch"):
            st.session_state.api_authorized = False
            st.rerun()

    if not settings.openai_calls_enabled:
        st.warning("Kill switch is active. The demo is read-only; no OpenAI calls can run.")
    if not os.getenv("OPENAI_API_KEY"):
        st.warning("OPENAI_API_KEY is not configured.")

    st.subheader("Today's safeguards")
    st.metric("Paid actions", f"{usage['jobs']} / {settings.max_normalization_jobs_per_day}")
    st.metric(
        "OpenAI API calls",
        f"{usage['api_calls']} used · {usage['reserved_api_calls']} reserved / "
        f"{settings.max_global_api_calls_per_day}",
    )
    st.caption(f"Tokens recorded today: {usage['total_tokens']:,}")
    paid_actions_ready = (
        st.session_state.api_authorized and settings.openai_calls_enabled
        and bool(os.getenv("OPENAI_API_KEY")) and bool(settings.demo_access_code)
    )
    st.subheader("Normalization batch")
    selected_batch = st.selectbox(
        "Domain",
        [row["section"] for row in domain_progress],
        format_func=lambda section: f"{section} · {DOMAIN_NAMES.get(section, section)}",
    )
    selected_progress = next(row for row in domain_progress if row["section"] == selected_batch)
    planned_calls = selected_progress["remaining"] * settings.normalization_runs
    available_calls = settings.max_global_api_calls_per_day - usage["reserved_api_calls"]
    st.caption(
        f"{selected_progress['normalized']} / {selected_progress['total']} normalized control "
        f"assessments · {selected_progress['remaining']} remaining · {planned_calls} planned API calls"
    )
    exceeds_quota = planned_calls > available_calls
    if exceeds_quota:
        st.warning(
            f"This batch needs {planned_calls} calls; today's remaining quota is {available_calls}."
        )
    if st.button(
        f"Normalize {selected_batch} domain", type="primary", width="stretch",
        disabled=not paid_actions_ready or not selected_progress["remaining"] or exceeds_quota,
    ):
        try:
            with st.spinner(f"Assessing each site {settings.normalization_runs} times…"):
                result = normalize_section(
                    connection,
                    classifier=openai_control_classifier(settings.model, settings.max_output_tokens),
                    model=settings.model, section_prefix=selected_batch, runs=settings.normalization_runs,
                    calls_enabled=settings.openai_calls_enabled,
                    max_jobs_per_day=settings.max_normalization_jobs_per_day,
                    max_api_calls_per_day=settings.max_global_api_calls_per_day,
                )
            if result.api_calls:
                st.success(
                    f"Normalized {result.processed_sites} {selected_batch} control assessments with "
                    f"{result.api_calls} API calls "
                    f"and {result.total_tokens:,} tokens."
                )
            else:
                st.info(f"Reused {result.cached_sites} cached assessments. No API calls made.")
            st.rerun()
        except NormalizationBlocked as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(f"Normalization failed safely: {exc}")

dashboard_tab, explorer_tab, evidence_tab = st.tabs(
    ["Executive dashboard", "Control explorer", "Ask evidence"]
)

with dashboard_tab:
    portfolio = portfolio_summary(connection)
    st.subheader("Portfolio overview")
    st.caption("A read-only management view across every loaded site and control.")
    metrics = st.columns(5)
    metrics[0].metric("Sites", portfolio["sites"])
    metrics[1].metric("Controls", portfolio["controls"])
    metrics[2].metric("Assessments", portfolio["assessments"])
    metrics[3].metric("Exceptions", portfolio["partial"] + portfolio["not_compliant"])
    metrics[4].metric("QA findings", portfolio["review_findings"])

    status_frame = pd.DataFrame([dict(row) for row in status_by_section(connection)])
    chart_frame = status_frame.pivot(index="section", columns="status", values="count").fillna(0).astype(int)
    for column in ["Compliant", "Partially Compliant", "Not Compliant", "Not Applicable"]:
        if column not in chart_frame:
            chart_frame[column] = 0
    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Assessment status by domain")
        st.bar_chart(
            chart_frame[["Compliant", "Partially Compliant", "Not Compliant", "Not Applicable"]],
            height=360, color=["#2E7D32", "#E9A23B", "#C62828", "#8B8F9A"],
        )
    with right:
        st.markdown("#### What the demo proves")
        st.info(
            "A reported status is not the same as normalized evidence. AC.2.1 shows how "
            "two sites can both report Compliant while their underlying practices differ."
        )
        st.metric(
            "Normalized control assessments",
            f"{portfolio['normalized']} / {portfolio['assessments']}",
        )
        st.metric("Not applicable", portfolio["not_applicable"])
        st.caption(
            "Normalization runs in controlled domain batches. Cached results are reused, and "
            "only remaining site-control responses incur model calls."
        )

    progress_frame = pd.DataFrame(domain_progress)
    progress_frame["Domain"] = progress_frame.apply(
        lambda row: f"{row['section']} · {DOMAIN_NAMES.get(row['section'], row['section'])}", axis=1
    )
    progress_frame["Progress"] = progress_frame.apply(
        lambda row: f"{row['normalized']} / {row['total']}", axis=1
    )
    st.markdown("#### Normalization progress by domain")
    st.dataframe(
        progress_frame[["Domain", "Progress", "remaining", "review_findings"]].rename(
            columns={"remaining": "Remaining", "review_findings": "QA findings"}
        ),
        hide_index=True, width="stretch",
    )

    catalog_frame = pd.DataFrame([dict(row) for row in control_catalog_rows(connection)])
    priority_frame = catalog_frame[
        (catalog_frame["partial"] > 0) | (catalog_frame["not_compliant"] > 0)
        | (catalog_frame["not_applicable"] > 0)
        | (catalog_frame["review_findings"] > 0)
    ].copy()
    priority_frame["Control"] = priority_frame["control_id"] + " · " + priority_frame["control_text"]
    st.markdown("#### Review queue")
    st.dataframe(
        priority_frame[["Control", "section_prefix", "partial", "not_compliant", "not_applicable", "review_findings"]].rename(
            columns={"section_prefix": "Domain", "partial": "Partial",
                     "not_compliant": "Not compliant", "not_applicable": "N/A",
                     "review_findings": "QA findings"}
        ),
        hide_index=True, width="stretch",
    )

with explorer_tab:
    catalog = [dict(row) for row in control_catalog_rows(connection)]
    sections = sorted({row["section_prefix"] for row in catalog})
    filter_col, control_col = st.columns([1, 3])
    with filter_col:
        selected_section = st.selectbox("Domain", sections, index=sections.index("AC"))
    candidates = [row for row in catalog if row["section_prefix"] == selected_section]
    labels = {row["control_id"]: f"{row['control_id']} · {row['control_text']}" for row in candidates}
    default_index = next((i for i, row in enumerate(candidates) if row["control_id"] == "AC.2.1"), 0)
    with control_col:
        selected_control = st.selectbox(
            "Control", [row["control_id"] for row in candidates], index=default_index,
            format_func=lambda control_id: labels[control_id],
        )

    rows = control_rows(connection, selected_control)
    st.subheader(labels[selected_control])
    if selected_control == "AC.2.1":
        st.info(
            "Both sites self-report Compliant. The detailed evidence reveals whether shared "
            "interactive accounts are actually used."
        )
    elif not any(row["normalized_value_json"] for row in rows):
        st.caption("Source evidence is available. This control has not yet been normalized.")

    comparison = []
    for row in rows:
        normalized = json.loads(row["normalized_value_json"]) if row["normalized_value_json"] else {}
        assessment = normalized.get("shared_accounts_used") or normalized.get("evidence_assessment", "Not normalized")
        comparison.append({
            "Site": row["site_name"], "Raw status": row["status_raw"],
            "Normalized assessment": assessment,
            "Reconciliation": row["status_reconciled"] or "Not normalized",
            "Agreement": row["llm_agreement_rate"] or "—",
            "QA review": "Yes" if row["needs_review"] else ("No" if row["needs_review"] is not None else "—"),
        })
    st.dataframe(pd.DataFrame(comparison), hide_index=True, width="stretch")

    for row in rows:
        badge = row["status_reconciled"] or row["status_raw"]
        with st.expander(f"{row['site_name']} · {badge}", expanded=selected_control == "AC.2.1"):
            raw_col, normalized_col = st.columns(2)
            with raw_col:
                st.markdown("**Raw source evidence**")
                st.markdown(f"**Reported status:** {row['status_raw']}")
                if selected_control == "AC.2.1":
                    st.markdown(f"**S.7:** {row['security_answer']}")
                st.write(row["detailed_description"])
                if row["implementation_considerations"]:
                    st.caption("Implementation considerations")
                    st.write(row["implementation_considerations"])
            with normalized_col:
                st.markdown("**Normalized assessment**")
                if row["normalized_value_json"]:
                    st.json(json.loads(row["normalized_value_json"]))
                    st.write(row["reconciliation_note"])
                    st.caption(
                        f"Model {row['model_version']} · Prompt {row['prompt_version']} · "
                        f"Agreement {row['llm_agreement_rate']}"
                    )
                else:
                    st.write("Not yet normalized.")

with evidence_tab:
    st.subheader("Ask the source evidence")
    st.caption(
        "Managed retrieval over the currently indexed synthetic ITRA PDFs. Answers show cited files "
        "and the retrieved evidence chunks."
    )
    rag_ready = paid_actions_ready and bool(settings.vector_store_id)
    if not settings.vector_store_id:
        st.info("RAG is not configured yet. Set OPENAI_VECTOR_STORE_ID after indexing the PDFs.")
    elif not rag_ready:
        st.info("Evidence search is available when paid actions are unlocked and the kill switch is off.")

    with st.form("rag_question_form"):
        question = st.text_input(
            "Question", placeholder="Which site describes shared interactive accounts, and what is the exception?",
            max_chars=1000, disabled=not rag_ready,
        )
        ask_clicked = st.form_submit_button("Ask evidence", disabled=not rag_ready, type="primary")

    if ask_clicked:
        try:
            with st.spinner("Searching the ITRA evidence…"):
                answer = ask_evidence(
                    connection, question, model=settings.model,
                    vector_store_id=settings.vector_store_id, max_results=settings.rag_max_results,
                    max_output_tokens=settings.max_output_tokens, calls_enabled=settings.openai_calls_enabled,
                    max_jobs_per_day=settings.max_normalization_jobs_per_day,
                    max_api_calls_per_day=settings.max_global_api_calls_per_day,
                )
            st.markdown(answer.text)
            if answer.citations:
                st.caption("Sources: " + " · ".join(c.filename for c in answer.citations))
            else:
                st.warning("The response contained no file citation. Treat it as unverified.")
            if answer.evidence:
                with st.expander(f"Retrieved evidence · {len(answer.evidence)} chunks"):
                    for index, snippet in enumerate(answer.evidence, start=1):
                        score = f" · relevance {snippet.score:.0%}" if snippet.score is not None else ""
                        st.markdown(f"**{index}. {snippet.filename}{score}**")
                        st.write(snippet.text)
            else:
                st.warning("No retrieved evidence chunks were returned for inspection.")
            st.caption(f"Response {answer.response_id} · {answer.total_tokens:,} tokens")
        except (NormalizationBlocked, ValueError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(f"Evidence query failed safely: {exc}")
