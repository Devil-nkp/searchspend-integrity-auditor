# SearchSpend Integrity Auditor 🛡️

> **Stop false Google Ads waste claims before they cost businesses money.**

SearchSpend Integrity Auditor is an accuracy-first financial analytics engine and interactive SaaS dashboard for Google Ads search marketing. It audits search-term visibility, calculates unrepresented search spend, and enforces conversion-lag maturity guards to prevent false-positive "wasted spend" claims.

Built on the `google-ads-recovery-core` foundation, this competition edition turns low-level financial domain models into an intuitive, high-precision audit platform.

---

## 🌟 Key Capabilities

1. **Integer-Micros Financial Precision (`Money`):**
   - Eliminates IEEE 754 floating-point rounding errors across millions of transactions by calculating and storing all currency amounts as integer micros (`cost_micros`).
   - Converts to `Decimal` only for display and unit operations. Rejects cross-currency aggregations.

2. **Search-Term Coverage Diagnostic (`CoverageSummary`):**
   - Google reports omit lower-volume queries from Search Terms Reports.
   - **Core Invariant:** Unrepresented spend is a reporting coverage gap. It is not evidence of wasted advertising spend.
   - Computes the mathematical visibility ratio: $\frac{\text{Visible Search Term Spend}}{\text{Eligible Campaign Spend}}$.
   - Categorizes coverage into `HIGH` (≥80%), `MEDIUM` (50%–79%), and `LOW` (<50%).
   - **Crucial Rule:** The unrepresented spend gap (e.g., $4,000 of $10,000) is **Unrepresented in search-term report** and **never** labeled as wasted spend.

3. **Conversion-Lag Maturity Guard (`AccuracyPolicy.maturity`):**
   - Conversion attribution takes days or weeks to mature.
   - Automatically quarantines recent clicks within a user-configurable attribution window (e.g., 7 days) as `IMMATURE`, preventing premature performance penalties.

4. **Zero-Conversion Waste Rejection Invariant:**
   - Programmatically enforces `can_use_zero_conversion_as_waste_proof() == False`.
   - Zero conversions alone is **never** standalone proof of waste; it requires verified business context and semantic mismatch.

5. **Multi-Dimensional Finding Confidence:**
   - Finding confidence requires confirmed advertiser business context and semantic confidence ≥ 0.95.
   - Automatically caps finding confidence at `MEDIUM` if account coverage is incomplete.

6. **Read-Only Human Governance:**
   - Automated write-back or mutation to Google Ads is prohibited. Every potential negative keyword recommendation remains subject to manual advertiser review.

---

## 🚀 Quickstart & Local Execution

### 1. Prerequisites
- Python `3.11`, `3.12`, `3.13`, or `< 3.15`
- Recommended: Virtual environment

### 2. Installation
```bash
# Clone or navigate into the repository
cd google-ads-recovery-v1

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"
```

### 3. Launch the Streamlit Dashboard
```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

### 4. Run the Full Test Suite
```bash
pytest
```
*Current test suite: 25 passed in < 0.15s.*

---

## 📊 Dashboard Navigation

The Streamlit web interface is styled in a modern dark navy SaaS aesthetic with six dedicated modules:

1. **Overview:** Executive KPI summary cards (Eligible Campaign Spend, Visible Spend, Coverage Ratio, Unrepresented Spend), maturity breakdown, and interactive Altair charts.
2. **Upload Reports:** Dual CSV uploaders for Google Ads *Search Terms* and *Campaign Performance* reports with flexible column mapping, currency validation, and 1-click sample downloads.
3. **Coverage Analysis:** Deep-dive analysis of search-term report opacity, coverage classification bands, and explanation of why hidden traffic is not waste.
4. **Conversion Maturity:** Interactive controls for audit reference date (`as_of_date`) and attribution lag (`conversion_lag_days`), with a live quarantined observations table.
5. **Audit Results:** Search-term review table with maturity badges, confidence status, CTR, spend formatting, search/campaign filters, and one-click CSV export.
6. **About Accuracy:** Full breakdown of the Accuracy Contract, comparison between typical industry tools and this engine, and the 6 confidence dimensions.

---

## 🔬 Benchmark Demonstration Dataset

When launched, SearchSpend Integrity Auditor automatically loads the canonical competition demonstration dataset (`demo_data/`):

- **Eligible Campaign Spend:** **$10,000.00 USD** (10,000,000,000 micros) across 3 Search campaigns.
- **Visible Search-Term Spend:** **$6,000.00 USD** (6,000,000,000 micros) across 8 diverse search terms.
- **Observed Coverage Ratio:** **60.0%** (`MEDIUM` coverage band).
- **Unrepresented Spend:** **$4,000.00 USD** (Unrepresented in search-term report. Unrepresented spend is a reporting coverage gap. It is not evidence of wasted advertising spend).
- **Maturity Segmentation (7-day lag as of 2026-10-15):**
  - **Mature Spend:** $4,800.00 (5 terms, including converting terms, mature zero-conv queries, and employment intent).
  - **Immature Quarantined Spend:** $1,200.00 (3 recent terms held back from waste attribution).
- **Confidence Capping:** Proves that even with 99% semantic confidence, findings are capped at `MEDIUM` due to the 60% coverage ratio.

*All demonstration records are explicitly labeled with the badge:* `SYNTHETIC DEMO DATA`.

---

## 🎙️ Wispr Flow Development Record

- **Voice-Assisted Requirement Engineering:** Product specifications, UI styling prompts, test matrix constraints, and iterative feature refinement were dictated by voice using **Wispr Flow** into Antigravity.
- **Development Record Transparency:** The core Python foundation (`recovery.domain`, `recovery.accuracy`, `recovery.google_ads.gaql`) predated this competition session. Wispr Flow was used to direct and accelerate the creation of the CSV ingestion pipeline (`recovery.csv_ingestion`), benchmark dataset generator (`recovery.demo_data`), audit runner (`recovery.audit`), test suite expansion, and the complete Streamlit UI (`app.py`).

---

## 🌐 Public Deployment Guide

This repository is ready for 1-click deployment on **Streamlit Community Cloud** or **Hugging Face Spaces**:

1. Push this repository to GitHub.
2. Visit [share.streamlit.io](https://share.streamlit.io) and link your GitHub account.
3. Select this repository, branch `main`, and main file path `app.py`.
4. Deploy! No database configuration, secrets, or API tokens are required to run the demonstration mode and CSV upload workflows.

---

## 📄 License & Intellectual Property

`google-ads-recovery-core` &copy; 2026. Built for transparency and accuracy in digital advertising analytics.
