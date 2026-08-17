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
    connect,
    control_catalog_rows,
    control_rows,
    ingest_fixtures,
    normalization_progress_by_section,
    portfolio_sites,
    portfolio_summary,
    status_by_section,
)
from itra_normalizer.normalization import (
    NormalizationBlocked,
    normalize_section,
    openai_control_classifier,
    usage_today,
)
from itra_normalizer.rag import ask_evidence


DOMAIN_NAMES = {
    "AC": "Access Control",
    "BC": "Business Continuity",
    "DI": "Data Integrity",
    "LG": "Logging",
    "NW": "Network Security",
    "PD": "Physical & Device",
    "TP": "Third Party",
    "VM": "Vulnerability Management",
}
DIMENSION_LABELS = {
    "individual_accounts_used": "Individual accounts used",
    "shared_accounts_used": "Shared interactive accounts used",
    "shared_account_management": "Shared-account credential management",
    "service_accounts_used": "Service accounts used",
    "privileged_accounts_used": "Privileged accounts used",
    "privileged_credentials_managed": "Privileged credential management",
    "access_review_frequency": "Access review frequency",
    "remote_access": "Remote access",
    "supplier_remote_access": "Supplier remote access",
    "mfa_for_remote_access": "MFA for remote access",
    "central_logging": "Central logging",
    "central_patching": "Central patching",
    "vulnerability_scanning": "Vulnerability scanning",
    "backup_enabled": "Backup enabled",
    "backup_restore_tested": "Backup restoration tested",
    "disaster_recovery_plan": "Disaster recovery plan",
    "network_segmentation": "Network segmentation",
    "removable_media_restricted": "Removable media restriction",
    "compensating_controls": "Compensating-control strength",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pdf_for_site(site_id: str) -> Path | None:
    number = site_id.split("-")[-1]
    matches = list((ROOT / "data/raw_pdfs").glob(f"SYN_ITRA_{number}_*.pdf"))
    return matches[0] if matches else None


def normalized_value(row) -> dict:
    return json.loads(row["normalized_value_json"]) if row["normalized_value_json"] else {}


st.set_page_config(page_title="ITRA Portfolio Explorer", page_icon="🛡️", layout="wide")
settings = get_settings()
connection = connect(settings.db_path)
ingest_fixtures(connection, ROOT / "data/parsed", ROOT / "data/control_catalog.json")
usage = usage_today(connection)
portfolio = portfolio_summary(connection)
sites = [dict(row) for row in portfolio_sites(connection)]
domain_progress = [dict(row) for row in normalization_progress_by_section(connection)]
ground_truth = load_json(ROOT / "data/portfolio_ground_truth.json")
portfolio_truth = load_json(ROOT / "data/portfolio_truth.json")
variation_matrix = portfolio_truth["site_variation_matrix"]
catalog = [dict(row) for row in control_catalog_rows(connection)]

if "api_authorized" not in st.session_state:
    st.session_state.api_authorized = False

st.title("ITRA Portfolio Explorer")
st.caption("From inconsistent assessment documents to comparable evidence and portfolio insight")

with st.sidebar:
    st.header("Demo portfolio")
    st.success("10 synthetic ITRAs loaded")
    st.metric("Controls per site", 32)
    st.caption("5 calibration · 5 validation · synthetic data only")

    with st.expander("Admin controls", expanded=False):
        st.caption("Technical runtime controls are separated from the stakeholder journey.")
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
            st.warning("Kill switch is active. No OpenAI calls can run.")
        if not os.getenv("OPENAI_API_KEY"):
            st.warning("OPENAI_API_KEY is not configured.")
        st.metric("Paid actions today", f"{usage['jobs']} / {settings.max_normalization_jobs_per_day}")
        st.caption(
            f"API calls: {usage['api_calls']} used · {usage['reserved_api_calls']} planned / "
            f"{settings.max_global_api_calls_per_day}\n\nTokens: {usage['total_tokens']:,}"
        )
        paid_actions_ready = (
            st.session_state.api_authorized
            and settings.openai_calls_enabled
            and bool(os.getenv("OPENAI_API_KEY"))
            and bool(settings.demo_access_code)
        )
        selected_batch = st.selectbox(
            "Normalization domain",
            [row["section"] for row in domain_progress],
            format_func=lambda section: f"{section} · {DOMAIN_NAMES.get(section, section)}",
        )
        selected_progress = next(row for row in domain_progress if row["section"] == selected_batch)
        planned_calls = selected_progress["remaining"] * settings.normalization_runs
        available_calls = settings.max_global_api_calls_per_day - usage["reserved_api_calls"]
        st.caption(
            f"{selected_progress['normalized']} / {selected_progress['total']} mapped · "
            f"{selected_progress['remaining']} remaining · {planned_calls} planned calls"
        )
        exceeds_quota = planned_calls > available_calls
        if exceeds_quota:
            st.warning(f"Batch requires {planned_calls} calls; today’s remaining quota is {available_calls}.")
        if st.button(
            f"Run {selected_batch} batch",
            type="primary",
            width="stretch",
            disabled=not paid_actions_ready or not selected_progress["remaining"] or exceeds_quota,
        ):
            try:
                with st.spinner(f"Assessing each site {settings.normalization_runs} times…"):
                    result = normalize_section(
                        connection,
                        classifier=openai_control_classifier(settings.model, settings.max_output_tokens),
                        model=settings.model,
                        section_prefix=selected_batch,
                        runs=settings.normalization_runs,
                        calls_enabled=settings.openai_calls_enabled,
                        max_jobs_per_day=settings.max_normalization_jobs_per_day,
                        max_api_calls_per_day=settings.max_global_api_calls_per_day,
                    )
                st.success(
                    f"Mapped {result.processed_sites} responses with {result.api_calls} API calls "
                    f"and {result.total_tokens:,} tokens."
                )
                st.rerun()
            except NormalizationBlocked as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Normalization failed safely: {exc}")

source_tab, answer_tab, insight_tab, explore_tab = st.tabs(
    ["1 · Source Assessments", "2 · Standardized Answer Space", "3 · Analysis & Insights", "4 · Ask & Explore"]
)

with source_tab:
    st.subheader("Start with the source assessments")
    st.info(
        "Ten sites assessed the same equipment against the same 32 controls. The structure is common, "
        "but local implementation evidence and wording differ."
    )
    cols = st.columns(4)
    cols[0].metric("Source documents", len(sites))
    cols[1].metric("Calibration set", sum(site["portfolio_cohort"] == "Calibration" for site in sites))
    cols[2].metric("Validation set", sum(site["portfolio_cohort"] == "Validation" for site in sites))
    cols[3].metric("Raw control responses", portfolio["assessments"])

    st.markdown("#### Explore the source portfolio")
    site_labels = {site["site_id"]: f"{site['site_name']} · {site['portfolio_cohort']}" for site in sites}
    selected_site_id = st.selectbox(
        "Assessment", [site["site_id"] for site in sites], format_func=lambda site_id: site_labels[site_id]
    )
    selected_site = next(site for site in sites if site["site_id"] == selected_site_id)
    source_cols = st.columns([3, 1])
    with source_cols[0]:
        st.markdown(f"**{selected_site['site_name']}**")
        st.write(f"Application: {selected_site['business_application']}")
        st.write(f"Cohort: **{selected_site['portfolio_cohort']}**")
        st.caption(
            "Calibration sites establish and test the answer space. Validation sites test whether "
            "new evidence patterns fit that space without silently forcing a match."
        )
    with source_cols[1]:
        pdf_path = pdf_for_site(selected_site_id)
        if pdf_path:
            st.download_button(
                "Download source PDF", data=pdf_path.read_bytes(), file_name=pdf_path.name,
                mime="application/pdf", width="stretch",
            )
    st.dataframe(
        pd.DataFrame(sites)[["site_name", "portfolio_cohort", "control_count", "normalized_count"]].rename(
            columns={"site_name": "Site", "portfolio_cohort": "Cohort", "control_count": "Controls",
                     "normalized_count": "Existing model mappings"}
        ),
        hide_index=True,
        width="stretch",
    )
    with st.expander("Why split calibration and validation?"):
        st.write(
            "The calibration set is used to establish a reusable answer space. The validation set then "
            "tests generalization. Site Harbor is deliberately retained as a validation outlier so that "
            "the demo can show how a new pattern should be surfaced for review."
        )

with answer_tab:
    st.subheader("Establish a reusable answer space")
    st.info(
        "Normalization here means defining the standard questions and allowed answers—not analysing every "
        "document repeatedly. Five calibration assessments expose recurring patterns; new documents are "
        "then mapped to the resulting structure."
    )
    dimension = st.selectbox(
        "Standardized dimension",
        list(DIMENSION_LABELS),
        format_func=lambda key: DIMENSION_LABELS[key],
    )
    calibration_sites = [site["site_name"] for site in sites if site["portfolio_cohort"] == "Calibration"]
    calibration_values = [variation_matrix[site][dimension] for site in calibration_sites]
    allowed_values = sorted(set(calibration_values))
    evidence_controls = ground_truth["sites"][0]["evidence"].get(dimension, [])

    answer_cols = st.columns([2, 2, 1])
    answer_cols[0].metric("Calibration examples", len(calibration_sites))
    answer_cols[1].metric("Observed answer categories", len(allowed_values))
    answer_cols[2].metric("Schema version", "v1")
    st.markdown(f"#### {DIMENSION_LABELS[dimension]}")
    st.write("**Categories observed in calibration:** " + " · ".join(f"`{value}`" for value in allowed_values))
    st.write("**Required fallbacks:** `Unknown / not documented` · `New pattern / review required`")
    st.caption("Evidence controls: " + ", ".join(evidence_controls))
    st.dataframe(
        pd.DataFrame({"Calibration site": calibration_sites, "Standardized answer": calibration_values}),
        hide_index=True,
        width="stretch",
    )
    with st.expander("Explore raw evidence behind this dimension", expanded=True):
        related_controls = evidence_controls or ["AC.2.1"]
        selected_control = st.selectbox("Evidence control", related_controls, key="answer_space_control")
        rows = control_rows(connection, selected_control)
        evidence_frame = pd.DataFrame([
            {
                "Site": row["site_name"],
                "Reported status": row["status_raw"],
                "Raw evidence": row["detailed_description"],
            }
            for row in rows if row["site_name"] in calibration_sites
        ])
        st.dataframe(evidence_frame, hide_index=True, width="stretch")
    st.warning(
        "A value not represented in this answer space must be marked as Unknown/New pattern and reviewed. "
        "It must not be silently forced into the nearest category."
    )

with insight_tab:
    st.subheader("Apply the answer space and analyse the portfolio")
    st.info(
        "Once every assessment is mapped to the same answer space, comparisons become ordinary structured "
        "analytics: counts, trends, outliers and evidence/status conflicts."
    )
    expected = portfolio_truth["expected_answers"]
    kpis = st.columns(4)
    kpis[0].metric("Sites using shared accounts", f"{expected['shared_accounts_count']} / 10")
    kpis[1].metric("Shared credentials in vault", f"{expected['shared_account_sites_using_privileged_vault_count']} / 6")
    kpis[2].metric("Logging gaps", len(expected["partial_or_missing_central_logging"]))
    kpis[3].metric("Security outlier", expected["security_outlier"])

    analysis_dimension = st.selectbox(
        "Explore a portfolio dimension",
        list(DIMENSION_LABELS),
        index=list(DIMENSION_LABELS).index("shared_accounts_used"),
        format_func=lambda key: DIMENSION_LABELS[key],
        key="analysis_dimension",
    )
    analysis_frame = pd.DataFrame([
        {"Site": site, "Standardized answer": values[analysis_dimension]}
        for site, values in variation_matrix.items()
    ])
    counts = analysis_frame["Standardized answer"].value_counts().rename_axis("Answer").to_frame("Sites")
    chart_col, table_col = st.columns([2, 3])
    with chart_col:
        st.bar_chart(counts, height=320, color="#1F6B87")
    with table_col:
        st.dataframe(analysis_frame, hide_index=True, width="stretch", height=320)

    st.markdown("#### Reported control status by domain")
    status_frame = pd.DataFrame([dict(row) for row in status_by_section(connection)])
    chart_frame = status_frame.pivot(index="section", columns="status", values="count").fillna(0).astype(int)
    for column in ["Compliant", "Partially Compliant", "Not Compliant", "Not Applicable"]:
        if column not in chart_frame:
            chart_frame[column] = 0
    st.bar_chart(
        chart_frame[["Compliant", "Partially Compliant", "Not Compliant", "Not Applicable"]],
        height=360,
        color=["#2E7D32", "#E9A23B", "#C62828", "#8B8F9A"],
    )

    with st.expander("Explore model reconciliation on the two reference ITRAs"):
        domains = sorted({row["section_prefix"] for row in catalog})
        selected_domain = st.selectbox("Domain", domains, key="insight_domain")
        candidates = [row for row in catalog if row["section_prefix"] == selected_domain]
        labels = {row["control_id"]: f"{row['control_id']} · {row['control_text']}" for row in candidates}
        selected_control = st.selectbox(
            "Control", list(labels), format_func=lambda control_id: labels[control_id], key="insight_control"
        )
        rows = control_rows(connection, selected_control)
        comparison = []
        for row in rows:
            value = normalized_value(row)
            if not value:
                continue
            comparison.append({
                "Site": row["site_name"],
                "Reported status": row["status_raw"],
                "Normalized evidence": value.get("shared_accounts_used") or value.get("evidence_assessment"),
                "Reconciliation": row["status_reconciled"],
                "QA review": "Yes" if row["needs_review"] else "No",
                "Agreement": row["llm_agreement_rate"],
            })
        st.dataframe(pd.DataFrame(comparison), hide_index=True, width="stretch")
        st.caption(
            "These are actual persisted model results. Portfolio mappings above use the synthetic benchmark "
            "so the stakeholder journey can be demonstrated without hundreds of additional API calls."
        )

with explore_tab:
    st.subheader("Ask questions and inspect the evidence")
    st.info(
        "Evidence search retrieves relevant passages from the indexed source PDFs and cites the files used. "
        "Structured portfolio questions are shown in Analysis & Insights; a combined SQL + evidence agent is "
        "the next product extension."
    )
    example_cols = st.columns(3)
    example_cols[0].write("**Evidence**\n\nWhere is a shared account described?")
    example_cols[1].write("**Comparison**\n\nHow do Indigo and Juniper differ?")
    example_cols[2].write("**Portfolio**\n\nWhich sites have logging gaps?")

    rag_ready = (
        st.session_state.api_authorized
        and settings.openai_calls_enabled
        and bool(os.getenv("OPENAI_API_KEY"))
        and bool(settings.vector_store_id)
    )
    if not settings.vector_store_id:
        st.warning("Evidence search is not configured. Set OPENAI_VECTOR_STORE_ID after indexing PDFs.")
    elif not rag_ready:
        st.caption("Evidence search is read-only until an administrator unlocks paid actions and disables the kill switch.")
    with st.form("rag_question_form"):
        question = st.text_input(
            "Question",
            placeholder="Which site describes shared interactive accounts, and what exception is documented?",
            max_chars=1000,
            disabled=not rag_ready,
        )
        ask_clicked = st.form_submit_button("Ask evidence", disabled=not rag_ready, type="primary")
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
                st.caption("Sources: " + " · ".join(c.filename for c in answer.citations))
            else:
                st.warning("The response contained no file citation. Treat it as unverified.")
            if answer.evidence:
                with st.expander(f"Retrieved evidence · {len(answer.evidence)} chunks"):
                    for index, snippet in enumerate(answer.evidence, start=1):
                        score = f" · relevance {snippet.score:.0%}" if snippet.score is not None else ""
                        st.markdown(f"**{index}. {snippet.filename}{score}**")
                        st.write(snippet.text)
            st.caption(f"Response {answer.response_id} · {answer.total_tokens:,} tokens")
        except (NormalizationBlocked, ValueError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(f"Evidence query failed safely: {exc}")
