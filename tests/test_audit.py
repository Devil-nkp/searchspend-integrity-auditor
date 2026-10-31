from datetime import date
from decimal import Decimal

from recovery.accuracy import AccuracyPolicy
from recovery.audit import run_audit
from recovery.demo_data import (
    DEMO_AS_OF_DATE,
    DEMO_CONVERSION_LAG_DAYS,
    get_demo_campaign_spend,
    get_demo_search_terms,
)
from recovery.domain import (
    CoverageBand,
    CoverageSummary,
    DataMaturity,
    FindingConfidence,
    summarize_coverage,
)


def test_audit_run_demo_dataset() -> None:
    st = get_demo_search_terms()
    cs = get_demo_campaign_spend()
    cov = summarize_coverage(st, cs)
    policy = AccuracyPolicy(conversion_lag_days=DEMO_CONVERSION_LAG_DAYS)

    audit = run_audit(
        search_terms=st,
        coverage_summary=cov,
        policy=policy,
        as_of=DEMO_AS_OF_DATE,
        business_context_confirmed=False,
        is_synthetic=True,
    )

    assert audit.total_observations == 8
    assert audit.total_spend_micros == 6_000_000_000
    assert audit.total_spend.format() == "USD 6000.00"
    assert audit.mature_count == 5
    assert audit.immature_count == 3
    assert audit.mature_spend_micros == 4_800_000_000
    assert audit.immature_spend_micros == 1_200_000_000

    # Without business context confirmation, finding confidence is INSUFFICIENT
    for row in audit.rows:
        assert row.confidence_status == FindingConfidence.INSUFFICIENT
        assert row.zero_conv_waste_allowed is False


def test_audit_low_coverage_caps_confidence_at_medium() -> None:
    st = get_demo_search_terms()
    # Create low coverage scenario (visible $4,000 vs eligible $10,000 -> 40% -> LOW band)
    cov = CoverageSummary(
        visible_search_term_cost_micros=4_000_000_000,
        eligible_search_campaign_cost_micros=10_000_000_000,
        currency_code="USD",
    )
    assert cov.band == CoverageBand.LOW
    policy = AccuracyPolicy(conversion_lag_days=DEMO_CONVERSION_LAG_DAYS)

    # Supply an external semantic score for a mature query
    target_query = "roofing jobs hiring entry level no experience"
    semantic_scores = {target_query: Decimal("0.99")}

    audit = run_audit(
        search_terms=st,
        coverage_summary=cov,
        policy=policy,
        as_of=DEMO_AS_OF_DATE,
        business_context_confirmed=True,
        semantic_scores=semantic_scores,
    )

    matching_rows = [r for r in audit.rows if r.search_term == target_query]
    assert len(matching_rows) == 1
    # Because coverage is LOW, confidence is capped at MEDIUM even though semantic_confidence = 0.99
    assert matching_rows[0].confidence_status == FindingConfidence.MEDIUM
    assert "capped at MEDIUM" in matching_rows[0].explanation


def test_audit_row_to_dict_export() -> None:
    st = get_demo_search_terms()[:1]
    cs = get_demo_campaign_spend()
    cov = summarize_coverage(st, cs)
    policy = AccuracyPolicy(conversion_lag_days=7)

    audit = run_audit(st, cov, policy, as_of=date(2026, 10, 15))
    row_dict = audit.rows[0].to_dict()

    assert "Search Term" in row_dict
    assert "Maturity" in row_dict
    assert "Confidence" in row_dict
    assert "Integrity Explanation" in row_dict
    assert row_dict["Search Term"] == st[0].search_term


def test_audit_spend_partition_invariants() -> None:
    """Verify Requirements 7 & 8:
    - Mature converting spend + mature zero-conv spend == mature spend.
    - Mature spend + immature spend == visible search-term spend.
    """
    st = get_demo_search_terms()
    cs = get_demo_campaign_spend()
    cov = summarize_coverage(st, cs)
    policy = AccuracyPolicy(conversion_lag_days=DEMO_CONVERSION_LAG_DAYS)

    audit = run_audit(
        search_terms=st,
        coverage_summary=cov,
        policy=policy,
        as_of=DEMO_AS_OF_DATE,
    )

    # 1. Requirement 7: mature converting + mature zero-conv == mature spend
    assert audit.is_mature_partition_valid is True
    assert (
        audit.converting_spend_micros + audit.zero_conv_spend_micros
        == audit.mature_spend_micros
    )
    assert audit.converting_spend_micros == 3_400_000_000  # $3,400.00
    assert audit.zero_conv_spend_micros == 1_400_000_000   # $1,400.00
    assert audit.mature_spend_micros == 4_800_000_000      # $4,800.00

    # 2. Requirement 8: mature spend + immature spend == visible search-term spend
    assert audit.is_spend_partition_valid is True
    assert (
        audit.mature_spend_micros + audit.immature_spend_micros
        == audit.total_spend_micros
    )
    assert audit.immature_spend_micros == 1_200_000_000    # $1,200.00
    assert audit.total_spend_micros == 6_000_000_000       # $6,000.00


def test_observation_post_dating_audit_reference_date() -> None:
    st = get_demo_search_terms()
    cov = CoverageSummary(
        visible_search_term_cost_micros=6_000_000_000,
        eligible_search_campaign_cost_micros=10_000_000_000,
        currency_code="USD",
    )
    policy = AccuracyPolicy(conversion_lag_days=7)

    # Set as_of earlier than observations (e.g. 2026-10-01 while observations are Oct 5..14)
    audit = run_audit(
        search_terms=st,
        coverage_summary=cov,
        policy=policy,
        as_of=date(2026, 10, 1),
    )

    future_rows = [r for r in audit.rows if r.observation_date > date(2026, 10, 1)]
    assert len(future_rows) > 0
    for row in future_rows:
        assert row.maturity_status == DataMaturity.POST_AUDIT
        assert "post-dates audit cutoff" in row.explanation
        assert "Post-Audit Date (Quarantine)" in row.status_label
        diff = (row.observation_date - date(2026, 10, 1)).days
        assert f"which is {diff} day(s) after audit reference date" in row.explanation
        # Invariant: post-audit observations can never contribute to retrospective waste claims
        assert row.zero_conv_waste_allowed is False


def test_post_audit_observations_distinguished_from_lag_quarantine() -> None:
    st = get_demo_search_terms()
    cov = CoverageSummary(
        visible_search_term_cost_micros=6_000_000_000,
        eligible_search_campaign_cost_micros=10_000_000_000,
        currency_code="USD",
    )
    # Demo observations span Oct 3 to Oct 14
    # Set as_of to Oct 13 with lag 3 days -> cutoff is Oct 10
    # Mature (<= Oct 10): Oct 3, 4, 5, 6, 7
    # Conversion-lag quarantine (Oct 11..Oct 13): Oct 12, Oct 13
    # Post-audit quarantine (> Oct 13): Oct 14
    policy = AccuracyPolicy(conversion_lag_days=3)
    audit = run_audit(
        search_terms=st,
        coverage_summary=cov,
        policy=policy,
        as_of=date(2026, 10, 13),
    )

    # Verify counts and spends are separately tracked and partitioned
    assert audit.mature_count > 0
    assert audit.lag_quarantine_count > 0
    assert audit.post_audit_count > 0

    assert audit.is_spend_partition_valid is True
    assert audit.is_mature_partition_valid is True
    assert audit.is_immature_subpartition_valid is True

    assert (
        audit.lag_quarantine_spend_micros + audit.post_audit_spend_micros
        == audit.immature_spend_micros
    )
    assert audit.mature_spend_micros + audit.immature_spend_micros == audit.total_spend_micros

