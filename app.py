from __future__ import annotations

import io
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path for direct execution and deployment
_SRC_DIR = str(Path(__file__).resolve().parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import altair as alt
import pandas as pd
import streamlit as st

from recovery.accuracy import AccuracyPolicy
from recovery.audit import AuditSummary, run_audit
from recovery.csv_ingestion import (
    CSVValidationError,
    QuarantinedRow,
    parse_campaign_spend_csv,
    parse_search_terms_csv,
    validate_compatibility,
)
from recovery.demo_data import (
    DEMO_AS_OF_DATE,
    DEMO_CONVERSION_LAG_DAYS,
    SYNTHETIC_DATA_BADGE,
    get_demo_campaign_spend,
    get_demo_csv_campaign_spend,
    get_demo_csv_search_terms,
    get_demo_search_terms,
)
from recovery.domain import (
    CampaignSpendObservation,
    CoverageBand,
    CoverageSummary,
    DataMaturity,
    FindingConfidence,
    Money,
    SearchTermObservation,
    summarize_coverage,
)

# Page configuration
st.set_page_config(
    page_title="SearchSpend Integrity Auditor",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Dark Navy SaaS CSS
st.markdown(
    """
    <style>
    /* Dark Navy Dashboard Aesthetics */
    .stApp {
        background-color: #0B0F19;
        color: #F1F5F9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Header branding */
    .brand-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #60A5FA 0%, #3B82F6 50%, #2563EB 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .brand-tagline {
        font-size: 1.05rem;
        color: #94A3B8;
        font-weight: 400;
        margin-bottom: 1.2rem;
    }

    /* Persistent Audit Status Ribbon */
    .audit-ribbon {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 10px;
        padding: 0.85rem 1.25rem;
        margin-bottom: 1.5rem;
        display: flex;
        flex-wrap: wrap;
        gap: 1.5rem;
        align-items: center;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
    }
    .ribbon-item {
        font-size: 0.9rem;
        color: #CBD5E1;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .ribbon-item strong {
        color: #F8FAFC;
    }
    .ribbon-pill {
        background: rgba(59, 130, 246, 0.15);
        color: #60A5FA;
        border: 1px solid rgba(59, 130, 246, 0.3);
        padding: 0.2rem 0.55rem;
        border-radius: 6px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-weight: 600;
        font-size: 0.85rem;
    }

    /* KPI Cards */
    .kpi-container {
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
        flex-wrap: wrap;
    }
    .kpi-card {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        flex: 1;
        min-width: 220px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.4);
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .kpi-card:hover {
        border-color: #3B82F6;
        transform: translateY(-2px);
    }
    .kpi-label {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94A3B8;
        font-weight: 600;
        margin-bottom: 0.4rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .kpi-value {
        font-size: 1.75rem;
        font-weight: 700;
        color: #F8FAFC;
        margin-bottom: 0.25rem;
    }
    .kpi-subtext {
        font-size: 0.84rem;
        color: #94A3B8;
        font-weight: 500;
    }

    /* Sidebar typography & contrast improvements */
    [data-testid="stSidebar"] {
        background-color: #0D1322;
    }
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown p {
        color: #E2E8F0 !important;
        font-size: 0.92rem;
        font-weight: 500;
    }
    [data-testid="stSidebar"] .stCaption {
        color: #94A3B8 !important;
        font-size: 0.84rem;
    }

    /* Status Badges */
    .badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-high {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10B981;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .badge-medium {
        background-color: rgba(245, 158, 11, 0.15);
        color: #F59E0B;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .badge-low {
        background-color: rgba(239, 68, 68, 0.15);
        color: #EF4444;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    .badge-demo {
        background-color: rgba(139, 92, 246, 0.18);
        color: #C4B5FD;
        border: 1px solid rgba(139, 92, 246, 0.35);
        font-size: 0.7rem;
        padding: 0.15rem 0.5rem;
    }

    /* Alerts & Banners */
    .demo-banner {
        background: linear-gradient(90deg, rgba(99, 102, 241, 0.12) 0%, rgba(139, 92, 246, 0.12) 100%);
        border: 1px solid rgba(139, 92, 246, 0.35);
        border-radius: 10px;
        padding: 0.85rem 1.25rem;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        font-size: 0.9rem;
        color: #C4B5FD;
    }

    .coverage-gap-banner {
        background: rgba(245, 158, 11, 0.08);
        border: 1px solid rgba(245, 158, 11, 0.25);
        border-left: 4px solid #F59E0B;
        border-radius: 8px;
        padding: 0.85rem 1.25rem;
        margin: 1.2rem 0;
        color: #FEF3C7;
        font-size: 0.92rem;
        line-height: 1.5;
    }

    .verification-card {
        background: rgba(16, 185, 129, 0.08);
        border: 1px solid rgba(16, 185, 129, 0.25);
        border-radius: 8px;
        padding: 0.8rem 1.2rem;
        margin: 1rem 0;
        color: #A7F3D0;
        font-size: 0.88rem;
    }

    .contract-card {
        background: #111827;
        border: 1px solid #1F2937;
        border-left: 4px solid #3B82F6;
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1rem;
    }

    .reconciliation-warning-card {
        background: rgba(239, 68, 68, 0.12);
        border: 1px solid rgba(239, 68, 68, 0.35);
        border-left: 4px solid #EF4444;
        border-radius: 8px;
        padding: 0.9rem 1.25rem;
        margin: 1rem 0;
        color: #FCA5A5;
        font-size: 0.92rem;
        line-height: 1.5;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def fmt_money(m: Money | None) -> str:
    """Format Money with thousand separators for clear UI display.

    Example: USD 10000.00 -> USD 10,000.00
    """
    if m is None:
        return "N/A"
    return f"{m.currency_code} {m.units:,.2f}"


def initialize_session_state() -> None:
    """Initialize app state with canonical benchmark demonstration dataset."""
    if "is_demo_mode" not in st.session_state:
        st.session_state.is_demo_mode = True
        st.session_state.search_terms = get_demo_search_terms()
        st.session_state.campaign_spend = get_demo_campaign_spend()
        st.session_state.coverage_summary = summarize_coverage(
            st.session_state.search_terms, st.session_state.campaign_spend
        )
        st.session_state.as_of_date = DEMO_AS_OF_DATE
        st.session_state.conversion_lag_days = DEMO_CONVERSION_LAG_DAYS
        st.session_state.business_context_confirmed = False
        st.session_state.currency_code = "USD"
        st.session_state.upload_warnings = []
        st.session_state.quarantined_rows = []


initialize_session_state()

# Navigation Sidebar
with st.sidebar:
    st.markdown("### 🛡️ Navigation")
    nav_selection = st.radio(
        "Go to",
        [
            "1. Overview",
            "2. Upload Reports",
            "3. Coverage Analysis",
            "4. Conversion Maturity",
            "5. Audit Results",
            "6. About Accuracy",
        ],
        index=0,
    )

    st.markdown("---")
    st.markdown("### ⚙️ Audit Controls")
    st.session_state.conversion_lag_days = st.slider(
        "Conversion Lag (Days)",
        min_value=0,
        max_value=30,
        value=st.session_state.conversion_lag_days,
        help="Attribution maturity delay. Recent traffic within this window is quarantined from waste claims.",
    )

    st.session_state.as_of_date = st.date_input(
        "Audit Reference Date",
        value=st.session_state.as_of_date,
        help="Reference date for calculating maturity cutoff.",
    )

    st.session_state.business_context_confirmed = st.checkbox(
        "Business Context Confirmed",
        value=st.session_state.business_context_confirmed,
        help="Verified products, services, operating geographies, and excluded intents.",
    )

    st.markdown("---")
    if st.button("🔄 Reset to Synthetic Benchmark Demo", use_container_width=True):
        st.session_state.is_demo_mode = True
        st.session_state.search_terms = get_demo_search_terms()
        st.session_state.campaign_spend = get_demo_campaign_spend()
        st.session_state.coverage_summary = summarize_coverage(
            st.session_state.search_terms, st.session_state.campaign_spend
        )
        st.session_state.as_of_date = DEMO_AS_OF_DATE
        st.session_state.conversion_lag_days = DEMO_CONVERSION_LAG_DAYS
        st.session_state.business_context_confirmed = False
        st.session_state.quarantined_rows = []
        st.success("Loaded canonical demonstration benchmark ($10k / $6k / 60% coverage).")
        st.rerun()

    st.markdown(
        "<div style='font-size:0.84rem; color:#94A3B8; margin-top:2rem; line-height:1.45;'>"
        "SearchSpend Integrity Auditor v1.0<br/>"
        "Powered by <code style='color:#60A5FA;'>recovery-core</code> v0.1.0<br/>"
        "Accuracy-First Financial Engine"
        "</div>",
        unsafe_allow_html=True,
    )


# Compute audit parameters and policy
policy = AccuracyPolicy(conversion_lag_days=st.session_state.conversion_lag_days)
audit_summary = run_audit(
    search_terms=st.session_state.search_terms,
    coverage_summary=st.session_state.coverage_summary,
    policy=policy,
    as_of=st.session_state.as_of_date,
    business_context_confirmed=st.session_state.business_context_confirmed,
    is_synthetic=st.session_state.is_demo_mode,
)

# Header Branding
st.markdown(
    """
    <div>
        <div class="brand-title">SearchSpend Integrity Auditor</div>
        <div class="brand-tagline">Stop false Google Ads waste claims before they cost businesses money.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Prominent Audit Status Ribbon (Requirements 3 & 5)
as_of_str = st.session_state.as_of_date.isoformat()
as_of_display = f"{as_of_str} [Fixed Synthetic Demo Date]" if st.session_state.is_demo_mode else as_of_str
lag_str = f"{st.session_state.conversion_lag_days} Days"
cutoff_date = st.session_state.as_of_date - timedelta(days=st.session_state.conversion_lag_days)
cutoff_str = cutoff_date.isoformat()
data_source_badge = (
    f'<span class="badge badge-demo">{SYNTHETIC_DATA_BADGE}</span>'
    if st.session_state.is_demo_mode
    else '<span class="badge badge-high">USER UPLOADED DATA</span>'
)

st.markdown(
    f"""
    <div class="audit-ribbon">
        <div class="ribbon-item">📅 <strong>Audit Reference Date:</strong> <span class="ribbon-pill">{as_of_display}</span></div>
        <div class="ribbon-item">⏳ <strong>Conversion-Lag Window:</strong> <span class="ribbon-pill">{lag_str}</span></div>
        <div class="ribbon-item">🔒 <strong>Maturity Cutoff Date:</strong> <span class="ribbon-pill">{cutoff_str}</span></div>
        <div class="ribbon-item">🗂️ <strong>Dataset:</strong> {data_source_badge}</div>
        <div class="ribbon-item">💰 <strong>Precision:</strong> <span class="ribbon-pill">Exact Integer Micros</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.is_demo_mode:
    st.markdown(
        f"""
        <div class="demo-banner">
            <span style="font-size:1.2rem;">🔬</span>
            <div>
                <strong>{SYNTHETIC_DATA_BADGE}:</strong> Currently displaying canonical synthetic benchmark data 
                with a <strong>fixed demonstration reference date of 2026-10-15 (not a live audit date)</strong>. 
                (Campaign Spend: <strong>$10,000.00</strong>, Visible Search Terms: <strong>$6,000.00</strong>, Coverage: <strong>60.0%</strong>). 
                All records are synthetic benchmark demonstrations created to test accuracy and coverage rules.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# SECTION 1: OVERVIEW
# ==============================================================================
if nav_selection == "1. Overview":
    st.subheader("Executive Audit Overview")

    if st.session_state.quarantined_rows:
        st.warning(
            f"⚠️ **Data Ingestion Alert:** {len(st.session_state.quarantined_rows)} row(s) were quarantined or excluded "
            "from this audit (e.g. clicks > impressions, malformed dates, non-search networks, or outside verified common date range). "
            "Inspect and export quarantined records under **2. Upload Reports** or **5. Audit Results**."
        )

    cov = st.session_state.coverage_summary
    band_class = "badge-high" if cov.band == CoverageBand.HIGH else ("badge-medium" if cov.band == CoverageBand.MEDIUM else "badge-low")

    # 4 Main KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        camp_money = Money(cov.eligible_search_campaign_cost_micros, cov.currency_code)
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Eligible Campaign Spend {f'<span class="badge badge-demo">DEMO</span>' if st.session_state.is_demo_mode else ''}</div>
                <div class="kpi-value">{fmt_money(camp_money)}</div>
                <div class="kpi-subtext">SEARCH & SEARCH_PARTNERS only</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        visible_money = Money(cov.visible_search_term_cost_micros, cov.currency_code)
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Visible Search-Term Spend {f'<span class="badge badge-demo">DEMO</span>' if st.session_state.is_demo_mode else ''}</div>
                <div class="kpi-value">{fmt_money(visible_money)}</div>
                <div class="kpi-subtext">Visible in uploaded search terms report</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        ratio_pct = f"{cov.ratio * 100:.1f}%" if cov.ratio is not None else "N/A"
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Observed Coverage Ratio</div>
                <div class="kpi-value">{ratio_pct} <span class="badge {band_class}">{cov.band.value}</span></div>
                <div class="kpi-subtext">Visibility diagnostic metric</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        unrep_money = Money(cov.unobserved_cost_micros, cov.currency_code)
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Unrepresented Spend {f'<span class="badge badge-demo">DEMO</span>' if st.session_state.is_demo_mode else ''}</div>
                <div class="kpi-value">{fmt_money(unrep_money)}</div>
                <div class="kpi-subtext">⚠️ Unrepresented in search-term report</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Reconciliation Discrepancy Warning (Correction 5)
    if cov.has_reconciliation_discrepancy:
        excess_money = Money(cov.reconciliation_excess_micros, cov.currency_code)
        raw_pct = f"{cov.raw_ratio * 100:.1f}%" if cov.raw_ratio else "N/A"
        st.markdown(
            f"""
            <div class="reconciliation-warning-card">
                ⚠️ <strong>Reconciliation Discrepancy Detected:</strong><br/>
                Visible search-term spend (<strong>{fmt_money(visible_money)}</strong>) exceeds eligible campaign spend (<strong>{fmt_money(camp_money)}</strong>) 
                by <strong>{fmt_money(excess_money)}</strong> (raw ratio: <strong>{raw_pct}</strong>).<br/>
                <em>The 100% capped coverage display does not hide this discrepancy.</em> Common causes:
                campaign performance report was filtered to a subset of campaigns, search terms report included non-search channels, 
                or date windows were misaligned. Please verify your source datasets.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Core Coverage Gap Invariant Banner (Requirement 2)
    st.markdown(
        """
        <div class="coverage-gap-banner">
            🛡️ <strong>Core Diagnostic Rule:</strong> 
            <strong>Unrepresented spend is a reporting coverage gap. It is not evidence of wasted advertising spend.</strong><br/>
            Google does not include low-volume queries in search-term reports. Treating this difference as waste is a critical reporting error.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Secondary Maturity Cards (Requirement 4: Contextual explanation for mature zero-conversion spend)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(
            label="Mature Spend (Eligible for Review)",
            value=fmt_money(audit_summary.mature_spend),
            delta=f"{audit_summary.mature_count} mature queries",
            delta_color="normal",
        )
    with m2:
        st.metric(
            label="Immature Spend (Lag Quarantine)",
            value=fmt_money(audit_summary.immature_spend),
            delta=f"{audit_summary.immature_count} queries in quarantine",
            delta_color="off",
        )
    with m3:
        st.metric(
            label="Mature Converting Spend",
            value=fmt_money(audit_summary.converting_spend),
            delta=f"{audit_summary.converting_count} converting queries",
            delta_color="normal",
        )
    with m4:
        st.metric(
            label="Mature Zero-Conv Spend",
            value=fmt_money(audit_summary.zero_conv_spend),
            delta="Context: 0 conv alone != waste",
            delta_color="inverse",
        )

    # Mathematical Partition Verification Badges (Requirements 7 & 8)
    v_col1, v_col2 = st.columns(2)
    with v_col1:
        mature_check = "✅ VERIFIED" if audit_summary.is_mature_partition_valid else "❌ FAILED"
        st.markdown(
            f"""
            <div class="verification-card">
                <span>{mature_check}</span>
                <div>
                    <strong>Mature Partition Integrity:</strong><br/>
                    Converting ({fmt_money(audit_summary.converting_spend)}) + Zero-Conv ({fmt_money(audit_summary.zero_conv_spend)}) = Mature Spend ({fmt_money(audit_summary.mature_spend)})
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with v_col2:
        spend_check = "✅ VERIFIED" if audit_summary.is_spend_partition_valid else "❌ FAILED"
        st.markdown(
            f"""
            <div class="verification-card">
                <span>{spend_check}</span>
                <div>
                    <strong>Visibility Partition Integrity:</strong><br/>
                    Mature ({fmt_money(audit_summary.mature_spend)}) + Immature ({fmt_money(audit_summary.immature_spend)}) = Visible Spend ({fmt_money(audit_summary.total_spend)})
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Visual Analytics with Improved Tooltips (Requirements 5 & 6)
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### 📊 Search Spend Visibility Breakdown")
        st.caption(
            f"Eligible Campaign Spend: {fmt_money(camp_money)} | "
            f"Visible Spend (search terms report) vs. Underrepresented (unobserved coverage gap)"
            f"{' (Source: Synthetic Benchmark Data)' if st.session_state.is_demo_mode else ''}"
        )

        visible_flt = float(Money(cov.visible_search_term_cost_micros, cov.currency_code).units)
        unrep_flt = float(Money(cov.unobserved_cost_micros, cov.currency_code).units)
        tot_flt = float(camp_money.units)

        df_coverage = pd.DataFrame(
            [
                {
                    "Category": "Visible Spend",
                    "Spend": visible_flt,
                    "Exact USD": f"${visible_flt:,.2f}",
                    "Percentage": f"{(visible_flt / tot_flt * 100):.1f}%",
                    "Classification": "Exposed in Google search_term_view",
                    "Audit Meaning": "Eligible for search query review",
                },
                {
                    "Category": "Underrepresented",
                    "Spend": unrep_flt,
                    "Exact USD": f"${unrep_flt:,.2f}",
                    "Percentage": f"{(unrep_flt / tot_flt * 100):.1f}%",
                    "Classification": "Reporting Coverage Gap",
                    "Audit Meaning": "Coverage gap — NOT evidence of waste",
                },
            ]
        )

        # High-contrast color scale distinguishing visible from underrepresented spend (Requirement 6)
        chart_cov = (
            alt.Chart(df_coverage)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
            .encode(
                x=alt.X(
                    "Category:N",
                    title="Reporting Category",
                    axis=alt.Axis(
                        labelAngle=0,
                        labelColor="#E2E8F0",
                        labelFontSize=12,
                        labelFontWeight="bold",
                        labelLimit=0,
                        titleColor="#F8FAFC",
                        titleFontSize=13,
                        titleFontWeight="bold",
                    ),
                ),
                y=alt.Y(
                    "Spend:Q",
                    title=f"Spend ({cov.currency_code})",
                    axis=alt.Axis(
                        labelColor="#E2E8F0",
                        labelFontSize=11,
                        titleColor="#F8FAFC",
                        titleFontSize=13,
                        titleFontWeight="bold",
                        gridColor="#1E293B",
                    ),
                ),
                color=alt.Color(
                    "Category:N",
                    scale=alt.Scale(
                        domain=["Visible Spend", "Underrepresented"],
                        range=["#2563EB", "#64748B"],
                    ),
                    legend=alt.Legend(
                        title="Coverage Status",
                        orient="bottom",
                        titleColor="#F8FAFC",
                        titleFontSize=12,
                        labelColor="#E2E8F0",
                        labelFontSize=11,
                        labelLimit=0,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("Category:N", title="Category"),
                    alt.Tooltip("Exact USD:N", title="Exact Amount (USD)"),
                    alt.Tooltip("Percentage:N", title="Share of Campaign Spend"),
                    alt.Tooltip("Classification:N", title="Data Classification"),
                    alt.Tooltip("Audit Meaning:N", title="Integrity Invariant"),
                ],
            )
            .properties(height=300)
        )
        st.altair_chart(chart_cov, use_container_width=True)

    with g2:
        st.markdown("#### ⏳ Conversion Maturity Breakdown")
        st.caption(
            f"Visible Search Spend: {fmt_money(visible_money)} | "
            f"Attribution window: {st.session_state.conversion_lag_days} days"
            f"{' (Source: Synthetic Benchmark Data)' if st.session_state.is_demo_mode else ''}"
        )

        conv_flt = float(audit_summary.converting_spend.units)
        zero_flt = float(audit_summary.zero_conv_spend.units)
        imm_flt = float(audit_summary.immature_spend.units)
        vis_tot = float(visible_money.units)

        mat_items = [
            {
                "Category": "Mature Converting",
                "Spend": conv_flt,
                "Exact USD": f"${conv_flt:,.2f}",
                "Percentage": f"{(conv_flt / vis_tot * 100):.1f}%" if vis_tot else "0.0%",
                "Evaluation Status": "Mature (Commercial intent verified)",
            },
            {
                "Category": "Mature Zero-Conv",
                "Spend": zero_flt,
                "Exact USD": f"${zero_flt:,.2f}",
                "Percentage": f"{(zero_flt / vis_tot * 100):.1f}%" if vis_tot else "0.0%",
                "Evaluation Status": "Mature (0 conv alone cannot prove waste)",
            },
        ]

        if audit_summary.post_audit_count > 0:
            lag_flt = float(audit_summary.lag_quarantine_spend.units)
            post_flt = float(audit_summary.post_audit_spend.units)
            mat_items.append({
                "Category": "Immature (Lag)",
                "Spend": lag_flt,
                "Exact USD": f"${lag_flt:,.2f}",
                "Percentage": f"{(lag_flt / vis_tot * 100):.1f}%" if vis_tot else "0.0%",
                "Evaluation Status": "Quarantined within conversion-lag delay",
            })
            mat_items.append({
                "Category": "Post-Audit Date",
                "Spend": post_flt,
                "Exact USD": f"${post_flt:,.2f}",
                "Percentage": f"{(post_flt / vis_tot * 100):.1f}%" if vis_tot else "0.0%",
                "Evaluation Status": "Post-dates audit cutoff; blocked from retrospective claims",
            })
            chart_domains = ["Mature Converting", "Mature Zero-Conv", "Immature (Lag)", "Post-Audit Date"]
            chart_ranges = ["#10B981", "#F59E0B", "#8B5CF6", "#EC4899"]
        else:
            mat_items.append({
                "Category": "Immature (Lag)",
                "Spend": imm_flt,
                "Exact USD": f"${imm_flt:,.2f}",
                "Percentage": f"{(imm_flt / vis_tot * 100):.1f}%" if vis_tot else "0.0%",
                "Evaluation Status": "Quarantined within conversion-lag delay",
            })
            chart_domains = ["Mature Converting", "Mature Zero-Conv", "Immature (Lag)"]
            chart_ranges = ["#10B981", "#F59E0B", "#8B5CF6"]

        df_maturity = pd.DataFrame(mat_items)

        chart_mat = (
            alt.Chart(df_maturity)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
            .encode(
                x=alt.X(
                    "Category:N",
                    title="Maturity Status",
                    axis=alt.Axis(
                        labelAngle=0,
                        labelColor="#E2E8F0",
                        labelFontSize=12,
                        labelFontWeight="bold",
                        labelLimit=0,
                        titleColor="#F8FAFC",
                        titleFontSize=13,
                        titleFontWeight="bold",
                    ),
                ),
                y=alt.Y(
                    "Spend:Q",
                    title=f"Spend ({cov.currency_code})",
                    axis=alt.Axis(
                        labelColor="#E2E8F0",
                        labelFontSize=11,
                        titleColor="#F8FAFC",
                        titleFontSize=13,
                        titleFontWeight="bold",
                        gridColor="#1E293B",
                    ),
                ),
                color=alt.Color(
                    "Category:N",
                    scale=alt.Scale(
                        domain=chart_domains,
                        range=chart_ranges,
                    ),
                    legend=alt.Legend(
                        title="Maturity Class",
                        orient="bottom",
                        titleColor="#F8FAFC",
                        titleFontSize=12,
                        labelColor="#E2E8F0",
                        labelFontSize=11,
                        labelLimit=0,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("Category:N", title="Category"),
                    alt.Tooltip("Exact USD:N", title="Exact Amount (USD)"),
                    alt.Tooltip("Percentage:N", title="Share of Visible Spend"),
                    alt.Tooltip("Evaluation Status:N", title="Policy Evaluation"),
                ],
            )
            .properties(height=300)
        )
        st.altair_chart(chart_mat, use_container_width=True)


# ==============================================================================
# SECTION 2: UPLOAD REPORTS
# ==============================================================================
elif nav_selection == "2. Upload Reports":
    st.subheader("Upload Google Ads Reports")
    st.markdown(
        "Upload standard Google Ads CSV export files. The auditor parses numerical amounts into **integer micros** "
        "using `Decimal` arithmetic to guarantee zero floating-point drift."
    )

    u1, u2 = st.columns(2)
    with u1:
        st.markdown("##### 1. Search Terms Report (CSV)")
        st_file = st.file_uploader(
            "Upload Search Terms Report",
            type=["csv"],
            key="st_uploader",
            help="CSV containing observed customer search terms, clicks, impressions, cost, and conversions.",
        )
        st.download_button(
            "📥 Download Sample Search Terms CSV",
            data=get_demo_csv_search_terms(),
            file_name="sample_search_terms.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with u2:
        st.markdown("##### 2. Campaign Performance Report (CSV)")
        cs_file = st.file_uploader(
            "Upload Campaign Spend Report",
            type=["csv"],
            key="cs_uploader",
            help="CSV containing campaign-level spend filtered to SEARCH and SEARCH_PARTNERS to serve as coverage denominator.",
        )
        st.download_button(
            "📥 Download Sample Campaign Spend CSV",
            data=get_demo_csv_campaign_spend(),
            file_name="sample_campaign_spend.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown("##### Account Currency & Ingestion Settings")
    default_curr = st.selectbox(
        "Default Currency Code (if omitted in CSV)",
        ["USD", "EUR", "GBP", "INR", "CAD", "AUD"],
        index=0,
    )

    if st_file is not None and cs_file is not None:
        if st.button("🚀 Process & Validate Uploaded Datasets", type="primary"):
            try:
                st_bytes = st_file.getvalue()
                cs_bytes = cs_file.getvalue()

                q_collector: list[QuarantinedRow] = []
                st_obs, st_warn = parse_search_terms_csv(
                    st_bytes, default_currency=default_curr, quarantined_out=q_collector
                )
                cs_obs, cs_warn = parse_campaign_spend_csv(
                    cs_bytes, default_currency=default_curr, quarantined_out=q_collector
                )

                report = validate_compatibility(
                    st_obs, cs_obs, quarantined_out=q_collector
                )
                if not report.is_compatible:
                    st.error(f"Dataset Incompatibility Error: {'; '.join(report.validation_messages)}")
                else:
                    st.session_state.is_demo_mode = False
                    st.session_state.search_terms = report.reconciled_search_terms
                    st.session_state.campaign_spend = report.reconciled_campaign_spend
                    st.session_state.coverage_summary = report.coverage_summary
                    st.session_state.upload_warnings = st_warn + cs_warn + report.validation_messages
                    st.session_state.quarantined_rows = report.quarantined_records
                    if report.date_max:
                        st.session_state.as_of_date = report.date_max

                    st.success(
                        f"Successfully ingested {len(report.reconciled_search_terms)} valid search terms and "
                        f"{len(report.reconciled_campaign_spend)} campaign records! "
                        f"Currency: {report.currency_code}. Date range: {report.date_min} to {report.date_max}."
                    )
                    st.rerun()

            except CSVValidationError as exc:
                st.error(f"CSV Validation Failed: {exc}")
            except Exception as exc:
                st.error(f"Unexpected parsing error: {exc}")

    if st.session_state.upload_warnings:
        with st.expander("⚠️ Ingestion Warnings"):
            for w in st.session_state.upload_warnings:
                st.caption(w)

    if st.session_state.quarantined_rows:
        st.markdown("---")
        st.markdown(f"#### 🛡️ Quarantined & Excluded Records ({len(st.session_state.quarantined_rows)})")
        st.caption(
            "The following records were excluded from audit spend coverage to protect metric integrity. "
            "Reasons include non-search networks, invalid clicks > impressions, malformed dates, duplicate keys, "
            "or dates outside the verified common date period."
        )
        df_quarantine = pd.DataFrame([q.to_dict() for q in st.session_state.quarantined_rows])
        st.dataframe(df_quarantine, use_container_width=True, hide_index=True)

        q_csv_buffer = io.StringIO()
        df_quarantine.to_csv(q_csv_buffer, index=False)
        st.download_button(
            label="📥 Export Quarantined Records to CSV",
            data=q_csv_buffer.getvalue(),
            file_name=f"quarantined_records_{st.session_state.as_of_date.isoformat()}.csv",
            mime="text/csv",
            key="download_quarantine_upload_tab",
        )


# ==============================================================================
# SECTION 3: COVERAGE ANALYSIS
# ==============================================================================
elif nav_selection == "3. Coverage Analysis":
    st.subheader("Search-Term Visibility & Coverage Analysis")
    cov = st.session_state.coverage_summary

    st.markdown(
        """
        Google Ads reports omit search queries with low impression volume from Search Terms Reports. 
        Traditional audit tools make a fatal mistake: they assume visible search terms represent 100% of search traffic, 
        or they label the unrepresented difference as 'hidden waste'.
        """
    )

    # Core Invariant Alert Box (Requirement 2)
    st.markdown(
        """
        <div class="coverage-gap-banner">
            🛡️ <strong>Accuracy Invariant:</strong> 
            <strong>Unrepresented spend is a reporting coverage gap. It is not evidence of wasted advertising spend.</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

    ratio_val = float(cov.ratio) * 100 if cov.ratio is not None else 0.0

    c1, c2, c3 = st.columns([1, 1, 1.2])
    with c1:
        st.metric("Eligible Campaign Spend", fmt_money(Money(cov.eligible_search_campaign_cost_micros, cov.currency_code)))
        st.metric("Visible Search-Term Spend", fmt_money(Money(cov.visible_search_term_cost_micros, cov.currency_code)))
    with c2:
        st.metric("Coverage Ratio", f"{ratio_val:.1f}%")
        st.metric("Coverage Classification Band", cov.band.value.upper())
    with c3:
        st.markdown(
            f"""
            <div class="contract-card">
                <strong>Accuracy Rule: Coverage Classification</strong><br/>
                <span class="badge badge-high">HIGH (≥80%)</span> Full account findings permitted.<br/>
                <span class="badge badge-medium">MEDIUM (50%–79%)</span> High-confidence findings capped at MEDIUM.<br/>
                <span class="badge badge-low">LOW (&lt;50%)</span> Account-level claims strictly prohibited.<br/>
                <hr style="border-color:#1F2937; margin:0.5rem 0;"/>
                <strong>Current Diagnostic:</strong> {cov.band.value.upper()} band ({ratio_val:.1f}%). 
                Finding confidence is capped to prevent unsupported assertions.
            </div>
            """,
            unsafe_allow_html=True,
        )

    if cov.has_reconciliation_discrepancy:
        excess_money = Money(cov.reconciliation_excess_micros, cov.currency_code)
        raw_pct = f"{cov.raw_ratio * 100:.1f}%" if cov.raw_ratio else "N/A"
        st.error(
            f"⚠️ **Reconciliation Discrepancy:** Visible search-term spend ({fmt_money(Money(cov.visible_search_term_cost_micros, cov.currency_code))}) "
            f"exceeds eligible campaign spend ({fmt_money(Money(cov.eligible_search_campaign_cost_micros, cov.currency_code))}) "
            f"by **{fmt_money(excess_money)}** (raw ratio: **{raw_pct}**).\n\n"
            "The 100% capped display does not conceal this defect. Please verify that both exports cover identical campaign and network scopes."
        )

    st.markdown("---")
    st.markdown("#### 🛡️ Why Unrepresented Spend is NOT 'Wasted Spend'")
    st.info(
        f"**Unrepresented in search-term report: {fmt_money(Money(cov.unobserved_cost_micros, cov.currency_code))}**\n\n"
        "Unrepresented spend is a reporting coverage gap. It is not evidence of wasted advertising spend.\n\n"
        "This $4,000 difference represents legitimate user queries that Google did not expose in search_term_view. "
        "These unrepresented queries frequently include high-performing long-tail searches and conversions. "
        "Under our **Accuracy Contract**, this gap is treated as *unrepresented diagnostic data*, never as waste."
    )


# ==============================================================================
# SECTION 4: CONVERSION MATURITY
# ==============================================================================
elif nav_selection == "4. Conversion Maturity":
    st.subheader("Conversion-Lag Maturity Guard")
    st.markdown(
        "Conversion attribution is not instantaneous. Customers may click an ad today and purchase 5, 14, or 28 days later. "
        "Marking recent zero-conversion clicks as 'waste' is mathematically invalid."
    )

    lag = st.session_state.conversion_lag_days
    as_of = st.session_state.as_of_date
    cutoff = as_of - timedelta(days=lag)

    st.markdown(
        f"""
        <div class="contract-card">
            <strong>Maturity Policy Parameters:</strong><br/>
            • <strong>Audit Reference Date:</strong> <code>{as_of.isoformat()}</code><br/>
            • <strong>Conversion-Lag Window:</strong> <code>{lag} days</code><br/>
            • <strong>Maturity Cutoff Date:</strong> <code>{cutoff.isoformat()}</code> (Observations on or before this date are <strong>MATURE</strong>; newer observations are <strong>IMMATURE</strong>).
        </div>
        """,
        unsafe_allow_html=True,
    )

    if audit_summary.post_audit_count > 0:
        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric(
                "Mature Observations",
                f"{audit_summary.mature_count} queries",
                f"{fmt_money(audit_summary.mature_spend)}",
            )
        with t2:
            st.metric(
                "Conversion-Lag Quarantine",
                f"{audit_summary.lag_quarantine_count} queries",
                f"{fmt_money(audit_summary.lag_quarantine_spend)}",
                delta_color="off",
            )
        with t3:
            st.metric(
                "Post-Audit Date Quarantine",
                f"{audit_summary.post_audit_count} queries",
                f"{fmt_money(audit_summary.post_audit_spend)}",
                delta_color="off",
            )
    else:
        t1, t2 = st.columns(2)
        with t1:
            st.metric(
                "Mature Observations",
                f"{audit_summary.mature_count} queries",
                f"{fmt_money(audit_summary.mature_spend)}",
            )
        with t2:
            st.metric(
                "Quarantined Immature Observations",
                f"{audit_summary.immature_count} queries",
                f"{fmt_money(audit_summary.immature_spend)}",
                delta_color="off",
            )

    # Verification Badges (Requirements 7 & 8)
    p1, p2 = st.columns(2)
    with p1:
        mature_valid = "✅ VERIFIED" if audit_summary.is_mature_partition_valid else "❌ FAILED"
        st.markdown(
            f"""
            <div class="verification-card">
                <span>{mature_valid}</span>
                <div>
                    <strong>Requirement 7 Verification:</strong><br/>
                    Mature Converting ({fmt_money(audit_summary.converting_spend)}) + Mature Zero-Conv ({fmt_money(audit_summary.zero_conv_spend)}) = Mature Spend ({fmt_money(audit_summary.mature_spend)})
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with p2:
        spend_valid = "✅ VERIFIED" if audit_summary.is_spend_partition_valid else "❌ FAILED"
        st.markdown(
            f"""
            <div class="verification-card">
                <span>{spend_valid}</span>
                <div>
                    <strong>Requirement 8 Verification:</strong><br/>
                    Mature Spend ({fmt_money(audit_summary.mature_spend)}) + Immature Spend ({fmt_money(audit_summary.immature_spend)}) = Visible Spend ({fmt_money(audit_summary.total_spend)})
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Contextual Explanation for Mature Zero-Conversion Spend (Requirement 4)
    st.markdown("#### 💡 Contextual Explanation: Mature Zero-Conversion Spend")
    st.info(
        f"**Mature Zero-Conversion Spend: {fmt_money(audit_summary.zero_conv_spend)}** across {audit_summary.zero_conv_count} queries.\n\n"
        "**Contextual note: Zero conversions alone cannot prove waste.** Even after the conversion-lag window has elapsed, "
        "advertising interactions with 0 recorded online conversions must not be automatically penalized. Key factors include:\n"
        "- **Untracked Offline Actions:** High-intent buyers often convert via direct phone calls, walk-ins, or offline invoices.\n"
        "- **Upper-Funnel Research Assists:** Preliminary searches educate customers who subsequently convert on branded or direct channels.\n"
        "- **Sample-Size Considerations:** Depending on an advertiser's baseline conversion rate and margins, low click volumes may be statistically inconclusive rather than proof of failure.\n"
        "- **Business-Model Latency:** Conversion cycles vary widely; while impulse consumer purchases convert quickly, high-consideration B2B or home services frequently require multi-week evaluation.\n\n"
        "**Accuracy Invariant:** Under our Accuracy Contract, zero conversions alone is **never** standalone proof of waste. "
        "Negative keyword recommendations require confirmed advertiser business context and semantic mismatch."
    )

    st.markdown("#### Quarantined Observations (Attribution In Progress & Post-Audit)")
    immature_rows = [r for r in audit_summary.rows if r.maturity_status in (DataMaturity.IMMATURE, DataMaturity.POST_AUDIT)]
    if immature_rows:
        df_imm = pd.DataFrame([r.to_dict() for r in immature_rows])
        df_imm["Spend"] = [fmt_money(Money(r.spend_micros, r.currency_code)) for r in immature_rows]
        st.dataframe(
            df_imm[["Search Term", "Campaign", "Observation Date", "Maturity", "Spend", "Clicks", "Conversions", "Integrity Explanation"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.write("No immature observations currently quarantined.")

    st.markdown("---")
    st.markdown("#### 🚫 The Zero-Conversion Non-Waste Invariant")
    st.warning(
        "**Invariant Enforced in Code:** `AccuracyPolicy.can_use_zero_conversion_as_waste_proof() == False`\n\n"
        "Even after traffic matures past the lag window, zero conversions alone is **never** accepted as standalone proof of waste."
    )


# ==============================================================================
# SECTION 5: AUDIT RESULTS
# ==============================================================================
elif nav_selection == "5. Audit Results":
    st.subheader("Search Term Audit Results")
    st.markdown("Transparent search-term review table. All metrics computed with integer-micros precision.")

    if st.session_state.is_demo_mode:
        st.markdown(
            f'<div style="margin-bottom:0.75rem;"><span class="badge badge-demo">{SYNTHETIC_DATA_BADGE}</span> '
            '<span style="font-size:0.85rem; color:#94A3B8;">Displaying canonical demonstration benchmark records.</span></div>',
            unsafe_allow_html=True,
        )

    # Context Alert
    if not st.session_state.business_context_confirmed:
        st.info(
            "ℹ️ **Business Context Not Confirmed:** Finding confidence is set to `INSUFFICIENT` for all terms. "
            "To unlock negative keyword recommendation confidence, check 'Business Context Confirmed' in the sidebar."
        )

    # Filter controls
    f1, f2, f3 = st.columns(3)
    with f1:
        campaigns = ["All Campaigns"] + sorted(list({r.campaign for r in audit_summary.rows}))
        selected_campaign = st.selectbox("Filter Campaign", campaigns)
    with f2:
        maturity_filter = st.selectbox(
            "Filter Maturity",
            ["All", "Mature Only", "Immature (Lag Quarantine) Only", "Post-Audit Only"],
        )
    with f3:
        conv_filter = st.selectbox("Filter Conversion Type", ["All", "Zero Conversions", "Converting"])

    # Filter rows
    filtered_rows = audit_summary.rows
    if selected_campaign != "All Campaigns":
        filtered_rows = [r for r in filtered_rows if r.campaign == selected_campaign]
    if maturity_filter == "Mature Only":
        filtered_rows = [r for r in filtered_rows if r.maturity_status == DataMaturity.MATURE]
    elif maturity_filter == "Immature (Lag Quarantine) Only":
        filtered_rows = [r for r in filtered_rows if r.maturity_status == DataMaturity.IMMATURE]
    elif maturity_filter == "Post-Audit Only":
        filtered_rows = [r for r in filtered_rows if r.maturity_status == DataMaturity.POST_AUDIT]

    if conv_filter == "Zero Conversions":
        filtered_rows = [r for r in filtered_rows if r.conversions == Decimal("0")]
    elif conv_filter == "Converting":
        filtered_rows = [r for r in filtered_rows if r.conversions > Decimal("0")]

    results_list = [r.to_dict() for r in filtered_rows]
    for item, row in zip(results_list, filtered_rows):
        item["Spend"] = fmt_money(Money(row.spend_micros, row.currency_code))
        item["Data Source"] = SYNTHETIC_DATA_BADGE if st.session_state.is_demo_mode else "USER UPLOADED DATA"

    df_results = pd.DataFrame(results_list)

    st.dataframe(df_results, use_container_width=True, hide_index=True)

    # Export to CSV with explicit synthetic demo labeling
    csv_buffer = io.StringIO()
    df_results.to_csv(csv_buffer, index=False)
    export_filename = (
        f"synthetic_demo_audit_{st.session_state.as_of_date.isoformat()}.csv"
        if st.session_state.is_demo_mode
        else f"search_spend_audit_{st.session_state.as_of_date.isoformat()}.csv"
    )
    st.download_button(
        label="📥 Export Audit Results to CSV",
        data=csv_buffer.getvalue(),
        file_name=export_filename,
        mime="text/csv",
    )

    if st.session_state.quarantined_rows:
        with st.expander(f"🛡️ Quarantined / Excluded Records ({len(st.session_state.quarantined_rows)})"):
            st.caption("Records excluded from audit spend coverage to protect metric integrity.")
            df_q_section5 = pd.DataFrame([q.to_dict() for q in st.session_state.quarantined_rows])
            st.dataframe(df_q_section5, use_container_width=True, hide_index=True)
            q_buffer_sec5 = io.StringIO()
            df_q_section5.to_csv(q_buffer_sec5, index=False)
            st.download_button(
                label="📥 Export Quarantined Records to CSV",
                data=q_buffer_sec5.getvalue(),
                file_name=f"quarantined_records_{st.session_state.as_of_date.isoformat()}.csv",
                mime="text/csv",
                key="download_quarantine_section5",
            )

    st.markdown("---")
    st.markdown(
        """
        <div style="font-size:0.85rem; color:#94A3B8;">
            <strong>Human Review Governance:</strong> SearchSpend Integrity Auditor operates strictly in <strong>read-only mode</strong>. 
            Automated write-back / mutation to Google Ads is deliberately disabled. Every potential exclusion must be previewed 
            and approved by an authorized account manager.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# SECTION 6: ABOUT ACCURACY
# ==============================================================================
elif nav_selection == "6. About Accuracy":
    st.subheader("The Accuracy Contract — Core Architecture")
    st.markdown(
        """
        Most PPC audit tools optimize for **finding volume and shock value** to sell services. 
        SearchSpend Integrity Auditor is architected around **truthfulness of output**.
        """
    )

    st.markdown("### Comparison: Standard Industry Practice vs. Accuracy-First Engine")

    comparison_data = [
        {
            "Audit Dimension": "Financial Precision",
            "Typical Industry Practice": "Standard IEEE 754 binary floats (leads to rounding drift across transactions)",
            "SearchSpend Integrity Auditor": "Exact integer micros (`cost_micros`) converted with `Decimal`",
        },
        {
            "Audit Dimension": "Unrepresented Search Queries",
            "Typical Industry Practice": "Naively treated as 100% visible, or gap labeled as 'wasted spend'",
            "SearchSpend Integrity Auditor": "Calculates `CoverageSummary` ratio. Invariant: Unrepresented spend is a reporting coverage gap. It is not evidence of wasted advertising spend.",
        },
        {
            "Audit Dimension": "Zero-Conversion Traffic",
            "Typical Industry Practice": "Asserts `0 conversions == waste` immediately after ad click",
            "SearchSpend Integrity Auditor": "Quarantines recent traffic in `conversion_lag_days`. Contextual rule: zero conversions alone cannot prove waste.",
        },
        {
            "Audit Dimension": "Negative Keywords",
            "Typical Industry Practice": "Blind LLM hallucinations pushed automatically to accounts",
            "SearchSpend Integrity Auditor": "Requires verified business context, checks existing exclusions, read-only governance",
        },
        {
            "Audit Dimension": "API Decoupling",
            "Typical Industry Practice": "Tight coupling to changing protobuf types",
            "SearchSpend Integrity Auditor": "Dedicated `GoogleAdsV26Adapter` boundary isolating domain models",
        },
    ]

    st.table(pd.DataFrame(comparison_data))

    st.markdown("### The 6 Confidence Dimensions")
    st.markdown(
        """
        1. **Data Coverage:** Visible search-term spend vs. comparable Search/Search Partners campaign spend.
        2. **Data Maturity:** Attribution cutoff verifying enough time has elapsed for conversion latency.
        3. **Business-Context Confidence:** Confirmed products, services, operating geographies, and excluded intents.
        4. **Semantic Confidence:** Model confidence that query intent strictly conflicts with verified business context.
        5. **Action Risk:** Evaluating blast radius of proposed negative keyword match types.
        6. **Existing Exclusion State:** Factoring in direct, shared-list, and account-level negatives already active.
        """
    )

    st.markdown("### Wispr Flow Development Record")
    st.info(
        "**Wispr Flow Dictation & Voice-Assisted Engineering:**\n\n"
        "Development requirements, architecture prompts, and iterative feedback for this competition edition "
        "were dictated by voice using **Wispr Flow** directly into Antigravity.\n\n"
        "*Honesty Note:* The core Python backend foundation (`recovery-core` domain models and GAQL queries) "
        "predated this competition build sprint. Wispr Flow was utilized to rapidly direct the creation of "
        "the CSV ingestion pipeline, synthetic benchmark dataset, audit engine, and Streamlit user interface."
    )
