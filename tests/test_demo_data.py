from datetime import date
from decimal import Decimal

from recovery.accuracy import AccuracyPolicy
from recovery.csv_ingestion import parse_campaign_spend_csv, parse_search_terms_csv
from recovery.demo_data import (
    DEMO_AS_OF_DATE,
    DEMO_CONVERSION_LAG_DAYS,
    get_demo_campaign_spend,
    get_demo_csv_campaign_spend,
    get_demo_csv_search_terms,
    get_demo_search_terms,
)
from recovery.domain import CoverageBand, DataMaturity, summarize_coverage


def test_demo_dataset_totals_and_coverage() -> None:
    st = get_demo_search_terms()
    cs = get_demo_campaign_spend()

    st_total = sum(t.cost_micros for t in st)
    cs_total = sum(c.cost_micros for c in cs)

    # Exactly $6,000.00 and $10,000.00 USD
    assert st_total == 6_000_000_000
    assert cs_total == 10_000_000_000

    cov = summarize_coverage(st, cs)
    assert cov.ratio == Decimal("0.60")
    assert cov.band == CoverageBand.MEDIUM
    assert cov.unobserved_cost_micros == 4_000_000_000


def test_demo_dataset_maturity_segmentation() -> None:
    st = get_demo_search_terms()
    policy = AccuracyPolicy(conversion_lag_days=DEMO_CONVERSION_LAG_DAYS)

    mature_terms = [t for t in st if policy.maturity(t.date, DEMO_AS_OF_DATE) == DataMaturity.MATURE]
    immature_terms = [t for t in st if policy.maturity(t.date, DEMO_AS_OF_DATE) == DataMaturity.IMMATURE]

    assert len(mature_terms) == 5
    assert len(immature_terms) == 3

    # Verify immature terms include zero-conversion traffic
    immature_zero_conv = [t for t in immature_terms if t.conversions == Decimal("0")]
    assert len(immature_zero_conv) == 2

    # Verify zero conversions is never standalone waste proof
    for t in st:
        assert policy.can_use_zero_conversion_as_waste_proof(
            observation_date=t.date, as_of=DEMO_AS_OF_DATE
        ) is False


def test_demo_csv_roundtrip_parsing() -> None:
    st_csv = get_demo_csv_search_terms()
    cs_csv = get_demo_csv_campaign_spend()

    st_obs, st_warnings = parse_search_terms_csv(st_csv)
    cs_obs, cs_warnings = parse_campaign_spend_csv(cs_csv)

    assert len(st_warnings) == 0
    assert len(cs_warnings) == 0
    assert sum(t.cost_micros for t in st_obs) == 6_000_000_000
    assert sum(c.cost_micros for c in cs_obs) == 10_000_000_000
