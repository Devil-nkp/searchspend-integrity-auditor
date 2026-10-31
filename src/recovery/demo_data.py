from __future__ import annotations

from datetime import date
from decimal import Decimal

from recovery.domain import (
    CampaignSpendObservation,
    CoverageBand,
    CoverageSummary,
    SearchTermObservation,
    summarize_coverage,
)

# Canonical benchmark figures required for the competition demo:
# Campaign spend: $10,000.00 (10,000,000,000 micros)
# Visible search-term spend: $6,000.00 (6,000,000,000 micros)
# Ratio: 60.0% -> MEDIUM CoverageBand
# Unobserved spend difference: $4,000.00 (4,000,000,000 micros)

DEMO_AS_OF_DATE = date(2026, 10, 15)
DEMO_CONVERSION_LAG_DAYS = 7  # Cutoff: 2026-10-08. <= 10-08 is MATURE, >= 10-09 is IMMATURE.
DEMO_CURRENCY = "USD"
SYNTHETIC_DATA_BADGE = "SYNTHETIC DEMO DATA"


def get_demo_campaign_spend() -> list[CampaignSpendObservation]:
    """Generates synthetic campaign spend records totaling exactly $10,000.00 USD.

    Clearly labeled as SYNTHETIC DEMO DATA.
    """
    return [
        CampaignSpendObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_res_roof",
            campaign_name="[DEMO] Search - Residential Roof Replacement",
            date=date(2026, 10, 5),
            network="SEARCH",
            cost_micros=5_000_000_000,  # $5,000.00
            currency_code=DEMO_CURRENCY,
        ),
        CampaignSpendObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_comm_roof",
            campaign_name="[DEMO] Search - Commercial Flat Roofing",
            date=date(2026, 10, 7),
            network="SEARCH",
            cost_micros=3_500_000_000,  # $3,500.00
            currency_code=DEMO_CURRENCY,
        ),
        CampaignSpendObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_leak_repair",
            campaign_name="[DEMO] Search - Emergency Leak Repair",
            date=date(2026, 10, 12),
            network="SEARCH_PARTNERS",
            cost_micros=1_500_000_000,  # $1,500.00
            currency_code=DEMO_CURRENCY,
        ),
    ]


def get_demo_search_terms() -> list[SearchTermObservation]:
    """Generates synthetic search term observations totaling exactly $6,000.00 USD.

    Features a deliberate mix:
    - Mature converting terms
    - Mature zero-conversion terms (illustrating the zero-conversion rule)
    - Mature semantic mismatch candidates (illustrating context requirements)
    - Immature terms (within conversion lag window) held back by maturity guard.

    All records clearly labeled as SYNTHETIC DEMO DATA.
    """
    return [
        # 1. Mature converting query (High intent, 5 conv) - $1,250.00
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_res_roof",
            campaign_name="[DEMO] Search - Residential Roof Replacement",
            ad_group_id="ag_metal_roof",
            ad_group_name="Metal Roofing",
            search_term="metal roof replacement estimate dallas",
            date=date(2026, 10, 3),  # Mature
            network="SEARCH",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="BROAD",
            targeting_status="NONE",
            triggering_keyword="roof replacement estimate",
            triggering_keyword_match_type="BROAD",
            impressions=120,
            clicks=18,
            cost_micros=1_250_000_000,  # $1,250.00
            conversions=Decimal("5"),
            conversions_value=Decimal("15000"),
            all_conversions=Decimal("5"),
            all_conversions_value=Decimal("15000"),
            currency_code=DEMO_CURRENCY,
        ),
        # 2. Mature converting query (High intent, 3 conv) - $950.00
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_res_roof",
            campaign_name="[DEMO] Search - Residential Roof Replacement",
            ad_group_id="ag_residential",
            ad_group_name="General Residential",
            search_term="best residential roofing contractor near me",
            date=date(2026, 10, 5),  # Mature
            network="SEARCH",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="PHRASE",
            targeting_status="NONE",
            triggering_keyword="residential roofing contractor",
            triggering_keyword_match_type="PHRASE",
            impressions=95,
            clicks=14,
            cost_micros=950_000_000,  # $950.00
            conversions=Decimal("3"),
            conversions_value=Decimal("9000"),
            all_conversions=Decimal("3"),
            all_conversions_value=Decimal("9000"),
            currency_code=DEMO_CURRENCY,
        ),
        # 3. Mature ZERO CONVERSION query (Educational intent) - $800.00
        # Demonstrates: 0 conversions does NOT equal waste proof!
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_res_roof",
            campaign_name="[DEMO] Search - Residential Roof Replacement",
            ad_group_id="ag_residential",
            ad_group_name="General Residential",
            search_term="diy roof repair manual pdf download",
            date=date(2026, 10, 4),  # Mature
            network="SEARCH",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="BROAD",
            targeting_status="NONE",
            triggering_keyword="roof repair manual",
            triggering_keyword_match_type="BROAD",
            impressions=180,
            clicks=22,
            cost_micros=800_000_000,  # $800.00
            conversions=Decimal("0"),
            conversions_value=Decimal("0"),
            all_conversions=Decimal("0"),
            all_conversions_value=Decimal("0"),
            currency_code=DEMO_CURRENCY,
        ),
        # 4. Mature commercial converting query - $1,200.00
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_comm_roof",
            campaign_name="[DEMO] Search - Commercial Flat Roofing",
            ad_group_id="ag_comm_tpo",
            ad_group_name="TPO Roofing",
            search_term="commercial flat roof membrane cost per sq ft",
            date=date(2026, 10, 6),  # Mature
            network="SEARCH",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="PHRASE",
            targeting_status="NONE",
            triggering_keyword="commercial flat roof cost",
            triggering_keyword_match_type="PHRASE",
            impressions=110,
            clicks=15,
            cost_micros=1_200_000_000,  # $1,200.00
            conversions=Decimal("4"),
            conversions_value=Decimal("28000"),
            all_conversions=Decimal("4"),
            all_conversions_value=Decimal("28000"),
            currency_code=DEMO_CURRENCY,
        ),
        # 5. Mature zero-conversion employment query (Semantic candidate, needs context) - $600.00
        # Demonstrates: Needs confirmed business context before high confidence!
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_comm_roof",
            campaign_name="[DEMO] Search - Commercial Flat Roofing",
            ad_group_id="ag_comm_gen",
            ad_group_name="General Commercial",
            search_term="roofing jobs hiring entry level no experience",
            date=date(2026, 10, 7),  # Mature
            network="SEARCH",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="BROAD",
            targeting_status="NONE",
            triggering_keyword="roofing hiring",
            triggering_keyword_match_type="BROAD",
            impressions=140,
            clicks=20,
            cost_micros=600_000_000,  # $600.00
            conversions=Decimal("0"),
            conversions_value=Decimal("0"),
            all_conversions=Decimal("0"),
            all_conversions_value=Decimal("0"),
            currency_code=DEMO_CURRENCY,
        ),
        # 6. IMMATURE zero-conversion commercial query - $450.00
        # Demonstrates: Held back by conversion-lag maturity guard!
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_comm_roof",
            campaign_name="[DEMO] Search - Commercial Flat Roofing",
            ad_group_id="ag_comm_tpo",
            ad_group_name="TPO Roofing",
            search_term="commercial tpo roofing contractor quote",
            date=date(2026, 10, 12),  # IMMATURE (3 days old vs 7-day lag)
            network="SEARCH",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="PHRASE",
            targeting_status="NONE",
            triggering_keyword="commercial tpo roofing",
            triggering_keyword_match_type="PHRASE",
            impressions=65,
            clicks=9,
            cost_micros=450_000_000,  # $450.00
            conversions=Decimal("0"),  # Immature, attribution still pending
            conversions_value=Decimal("0"),
            all_conversions=Decimal("0"),
            all_conversions_value=Decimal("0"),
            currency_code=DEMO_CURRENCY,
        ),
        # 7. IMMATURE converting emergency repair query - $500.00
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_leak_repair",
            campaign_name="[DEMO] Search - Emergency Leak Repair",
            ad_group_id="ag_emergency",
            ad_group_name="Emergency Tarping",
            search_term="emergency roof tarp service 24 hours",
            date=date(2026, 10, 14),  # IMMATURE (1 day old)
            network="SEARCH_PARTNERS",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="EXACT",
            targeting_status="NONE",
            triggering_keyword="emergency roof tarp service",
            triggering_keyword_match_type="EXACT",
            impressions=40,
            clicks=7,
            cost_micros=500_000_000,  # $500.00
            conversions=Decimal("1"),
            conversions_value=Decimal("2500"),
            all_conversions=Decimal("1"),
            all_conversions_value=Decimal("2500"),
            currency_code=DEMO_CURRENCY,
        ),
        # 8. IMMATURE zero-conversion emergency query - $250.00
        # Demonstrates: Held back by conversion-lag maturity guard!
        SearchTermObservation(
            customer_id="DEMO-941-882-0199",
            campaign_id="c_leak_repair",
            campaign_name="[DEMO] Search - Emergency Leak Repair",
            ad_group_id="ag_emergency",
            ad_group_name="Emergency Tarping",
            search_term="water leak ceiling repair cost estimate",
            date=date(2026, 10, 13),  # IMMATURE (2 days old)
            network="SEARCH_PARTNERS",
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type="BROAD",
            targeting_status="NONE",
            triggering_keyword="leak repair cost",
            triggering_keyword_match_type="BROAD",
            impressions=35,
            clicks=5,
            cost_micros=250_000_000,  # $250.00
            conversions=Decimal("0"),
            conversions_value=Decimal("0"),
            all_conversions=Decimal("0"),
            all_conversions_value=Decimal("0"),
            currency_code=DEMO_CURRENCY,
        ),
    ]


def get_demo_csv_search_terms() -> str:
    """Return CSV formatted text for demo search terms to enable user export/download."""
    headers = [
        "Search term",
        "Campaign",
        "Ad group",
        "Date",
        "Network",
        "Match type",
        "Keyword",
        "Impressions",
        "Clicks",
        "Cost",
        "Conversions",
        "Conv. value",
        "Currency",
    ]
    lines = [",".join(headers)]
    for st in get_demo_search_terms():
        row = [
            f'"{st.search_term}"',
            f'"{st.campaign_name}"',
            f'"{st.ad_group_name}"',
            st.date.isoformat(),
            st.network,
            st.search_term_match_type,
            f'"{st.triggering_keyword or ""}"',
            str(st.impressions),
            str(st.clicks),
            f"{st.cost.units:.2f}",
            str(st.conversions),
            str(st.conversions_value),
            st.currency_code,
        ]
        lines.append(",".join(row))
    return "\n".join(lines)


def get_demo_csv_campaign_spend() -> str:
    """Return CSV formatted text for demo campaign spend to enable user export/download."""
    headers = [
        "Campaign",
        "Date",
        "Network",
        "Cost",
        "Currency",
    ]
    lines = [",".join(headers)]
    for cs in get_demo_campaign_spend():
        cost_units = Decimal(cs.cost_micros) / Decimal("1000000")
        row = [
            f'"{cs.campaign_name}"',
            cs.date.isoformat(),
            cs.network,
            f"{cost_units:.2f}",
            cs.currency_code,
        ]
        lines.append(",".join(row))
    return "\n".join(lines)
