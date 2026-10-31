from datetime import date
from decimal import Decimal

import pytest

from recovery.csv_ingestion import (
    CSVValidationError,
    QuarantinedRow,
    parse_campaign_spend_csv,
    parse_date,
    parse_decimal_metric,
    parse_integer_metric,
    parse_money_to_micros,
    parse_search_terms_csv,
    validate_compatibility,
)
from recovery.domain import CoverageBand


def test_parse_money_to_micros_precision() -> None:
    assert parse_money_to_micros("$1,234.56") == 1_234_560_000
    assert parse_money_to_micros("10.00") == 10_000_000
    assert parse_money_to_micros("0") == 0
    assert parse_money_to_micros("") == 0
    assert parse_money_to_micros("-") == 0


def test_parse_money_rejects_binary_floats() -> None:
    with pytest.raises(TypeError):
        parse_money_to_micros(1234.56)  # float prohibited!


def test_parse_date_formats() -> None:
    assert parse_date("2026-10-15") == date(2026, 10, 15)
    assert parse_date("10/15/2026") == date(2026, 10, 15)
    assert parse_date("15-10-2026") == date(2026, 10, 15)
    with pytest.raises(CSVValidationError):
        parse_date("not-a-date")


def test_parse_search_terms_csv_success() -> None:
    csv_text = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"roof repair dallas","Search - Roof","50.00",5,50,2026-10-01,USD
"emergency tpo leak","Search - Roof","120.50",8,80,2026-10-02,USD
"""
    obs, warnings = parse_search_terms_csv(csv_text, default_currency="USD")
    assert len(obs) == 2
    assert obs[0].search_term == "roof repair dallas"
    assert obs[0].cost_micros == 50_000_000
    assert obs[0].currency_code == "USD"
    assert obs[1].cost_micros == 120_500_000


def test_parse_search_terms_csv_missing_required_column() -> None:
    bad_csv = """Campaign,Cost,Clicks\nSearch - Roof,50.00,5"""
    with pytest.raises(CSVValidationError) as exc_info:
        parse_search_terms_csv(bad_csv)
    assert "Search term" in str(exc_info.value)


def test_parse_search_terms_csv_cross_currency_rejected() -> None:
    bad_csv = """Search term,Cost,Currency,Date
query 1,50.00,USD,2026-10-01
query 2,50.00,EUR,2026-10-01
"""
    with pytest.raises(CSVValidationError) as exc_info:
        parse_search_terms_csv(bad_csv)
    assert "Multiple currencies detected" in str(exc_info.value)


def test_parse_campaign_spend_csv_success() -> None:
    csv_text = """Campaign,Date,Network,Cost,Currency
"Search - Roofing",2026-10-01,SEARCH,1000.00,USD
"Search - Repair",2026-10-01,SEARCH_PARTNERS,500.00,USD
"""
    obs, warnings = parse_campaign_spend_csv(csv_text)
    assert len(obs) == 2
    assert obs[0].cost_micros == 1_000_000_000
    assert obs[1].cost_micros == 500_000_000


def test_validate_compatibility_success() -> None:
    st_csv = """Search term,Cost,Currency,Date,Network\nquery 1,600.00,USD,2026-10-01,SEARCH"""
    cs_csv = """Campaign,Cost,Currency,Date,Network\ncamp 1,1000.00,USD,2026-10-01,SEARCH"""
    st_obs, _ = parse_search_terms_csv(st_csv)
    cs_obs, _ = parse_campaign_spend_csv(cs_csv)

    report = validate_compatibility(st_obs, cs_obs)
    assert report.is_compatible is True
    assert report.currency_code == "USD"
    assert report.coverage_summary is not None
    assert report.coverage_summary.ratio == Decimal("0.6")
    assert report.coverage_summary.band == CoverageBand.MEDIUM
    assert report.coverage_summary.unobserved_cost_micros == 400_000_000


def test_validate_compatibility_currency_mismatch() -> None:
    st_csv = """Search term,Cost,Currency,Date\nquery 1,600.00,USD,2026-10-01"""
    cs_csv = """Campaign,Cost,Currency,Date\ncamp 1,1000.00,GBP,2026-10-01"""
    st_obs, _ = parse_search_terms_csv(st_csv)
    cs_obs, _ = parse_campaign_spend_csv(cs_csv)

    report = validate_compatibility(st_obs, cs_obs)
    assert report.is_compatible is False
    assert "Currency mismatch" in report.validation_messages[0]


def test_parse_csv_with_leading_metadata_lines() -> None:
    raw_google_export = """Search terms report
October 1, 2026 - October 15, 2026

Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"commercial tpo repair","Commercial Roofing","450.00",10,100,2026-10-05,USD
"""
    obs, warnings = parse_search_terms_csv(raw_google_export)
    assert len(obs) == 1
    assert obs[0].search_term == "commercial tpo repair"
    assert obs[0].cost_micros == 450_000_000


def test_parse_csv_skips_summary_total_rows() -> None:
    raw_csv = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"tpo membrane installation","Commercial Roofing","300.00",5,50,2026-10-05,USD
"Total: Account","--","300.00",5,50,2026-10-05,USD
"""
    obs, warnings = parse_search_terms_csv(raw_csv)
    assert len(obs) == 1
    assert obs[0].search_term == "tpo membrane installation"
    assert any("Skipped Google Ads summary total row" in w for w in warnings)


def test_validate_compatibility_disjoint_dates() -> None:
    st_csv = """Search term,Cost,Currency,Date\nquery 1,600.00,USD,2026-08-01"""
    cs_csv = """Campaign,Cost,Currency,Date\ncamp 1,1000.00,USD,2026-10-01"""
    st_obs, _ = parse_search_terms_csv(st_csv)
    cs_obs, _ = parse_campaign_spend_csv(cs_csv)

    report = validate_compatibility(st_obs, cs_obs)
    assert report.is_compatible is False
    assert "Date range mismatch" in report.validation_messages[0]


def test_duplicate_search_term_observation_deduplicated() -> None:
    duplicate_csv = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"metal roof repair","Search - Roof","50.00",5,50,2026-10-01,USD
"metal roof repair","Search - Roof","50.00",5,50,2026-10-01,USD
"""
    obs, warnings = parse_search_terms_csv(duplicate_csv)
    # Deduplication policy: second row is skipped to prevent spend inflation
    assert len(obs) == 1
    assert obs[0].cost_micros == 50_000_000  # Spend NOT inflated to $100
    assert any("Duplicate observation" in w for w in warnings)


def test_malformed_and_missing_dates_are_quarantined_not_defaulted() -> None:
    bad_dates_csv = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"good query","Search - Roof","50.00",5,50,2026-10-01,USD
"bad date query","Search - Roof","50.00",5,50,not-a-valid-date,USD
"missing date query","Search - Roof","50.00",5,50,,USD
"""
    obs, warnings = parse_search_terms_csv(bad_dates_csv)
    assert len(obs) == 1
    assert obs[0].search_term == "good query"
    assert any("Malformed date 'not-a-valid-date'" in w for w in warnings)
    assert any("Missing required observation date" in w for w in warnings)


def test_clicks_exceeding_impressions_are_quarantined_not_clamped() -> None:
    bad_metrics_csv = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"valid query","Search - Roof","50.00",5,50,2026-10-01,USD
"corrupt query","Search - Roof","100.00",25,10,2026-10-01,USD
"""
    obs, warnings = parse_search_terms_csv(bad_metrics_csv)
    # Row with clicks > impressions must be quarantined, NOT clamped
    assert len(obs) == 1
    assert obs[0].search_term == "valid query"
    assert any("clicks (25) exceeds impressions (10)" in w for w in warnings)


def test_date_compatibility_calculates_over_verified_common_period() -> None:
    # Search terms: Oct 1 ($100), Oct 5 ($200), Oct 10 ($300) -> range Oct 1 to Oct 10
    st_csv = """Search term,Campaign,Cost,Date,Currency,Network
query 1,Roofing,100.00,2026-10-01,USD,SEARCH
query 2,Roofing,200.00,2026-10-05,USD,SEARCH
query 3,Roofing,300.00,2026-10-10,USD,SEARCH
"""
    # Campaign spend: Oct 5 ($500), Oct 10 ($500), Oct 20 ($1000) -> range Oct 5 to Oct 20
    cs_csv = """Campaign,Cost,Date,Currency,Network
Roofing,500.00,2026-10-05,USD,SEARCH
Roofing,500.00,2026-10-10,USD,SEARCH
Roofing,1000.00,2026-10-20,USD,SEARCH
"""
    st_obs, _ = parse_search_terms_csv(st_csv)
    cs_obs, _ = parse_campaign_spend_csv(cs_csv)

    report = validate_compatibility(st_obs, cs_obs)
    assert report.is_compatible is True
    assert report.has_date_reconciliation is True
    # Verified common period is Oct 5 to Oct 10
    assert report.date_min == date(2026, 10, 5)
    assert report.date_max == date(2026, 10, 10)
    # Over Oct 5..10: visible spend = $200 + $300 = $500, eligible campaign spend = $500 + $500 = $1,000
    assert report.coverage_summary is not None
    assert report.coverage_summary.visible_search_term_cost_micros == 500_000_000
    assert report.coverage_summary.eligible_search_campaign_cost_micros == 1_000_000_000
    assert report.coverage_summary.ratio == Decimal("0.5")
    assert report.coverage_summary.band == CoverageBand.MEDIUM
    assert any("Date range reconciliation" in m for m in report.validation_messages)


def test_reconciliation_warning_when_visible_exceeds_eligible() -> None:
    st_csv = """Search term,Cost,Currency,Date,Network\nquery 1,1200.00,USD,2026-10-01,SEARCH"""
    cs_csv = """Campaign,Cost,Currency,Date,Network\ncamp 1,1000.00,USD,2026-10-01,SEARCH"""
    st_obs, _ = parse_search_terms_csv(st_csv)
    cs_obs, _ = parse_campaign_spend_csv(cs_csv)

    report = validate_compatibility(st_obs, cs_obs)
    assert report.is_compatible is True
    assert report.coverage_summary is not None
    # Ratio is capped at Decimal("1")
    assert report.coverage_summary.ratio == Decimal("1")
    # But raw_ratio and discrepancy are exposed
    assert report.coverage_summary.has_reconciliation_discrepancy is True
    assert report.coverage_summary.raw_ratio == Decimal("1.2")
    assert report.coverage_summary.reconciliation_excess_micros == 200_000_000
    assert any("Reconciliation warning" in m for m in report.validation_messages)


def test_parse_money_to_micros_handles_google_ads_double_dash() -> None:
    # Google Ads exports standard null/unrecorded values as '--'
    assert parse_money_to_micros("--") == 0
    assert parse_money_to_micros("---") == 0
    assert parse_money_to_micros("N/A") == 0
    assert parse_money_to_micros("null") == 0


def test_parse_integer_metric_and_commas() -> None:
    assert parse_integer_metric("1,250") == 1250
    assert parse_integer_metric("25,000") == 25000
    assert parse_integer_metric("--") == 0
    assert parse_integer_metric("0") == 0
    assert parse_integer_metric(None) == 0


def test_parse_decimal_metric_strips_currency_symbols() -> None:
    assert parse_decimal_metric("$225.50") == Decimal("225.50")
    assert parse_decimal_metric("€150.00") == Decimal("150.00")
    assert parse_decimal_metric("£99.99") == Decimal("99.99")
    assert parse_decimal_metric("--") == Decimal("0")


def test_parse_search_terms_commas_in_impressions_not_quarantined() -> None:
    csv_text = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"commercial roofing","Campaign 1","100.00",50,"1,250",2026-10-01,USD
"""
    obs, warnings = parse_search_terms_csv(csv_text)
    assert len(obs) == 1
    assert obs[0].impressions == 1250
    assert obs[0].clicks == 50
    # Crucially, clicks (50) is NOT greater than impressions (1,250), so row is NOT quarantined!
    assert not any("quarantined" in w for w in warnings)


def test_parse_search_terms_with_distinct_keywords_same_query_not_discarded() -> None:
    # The same query can legitimately trigger via different keywords or match types in Google Ads
    csv_text = """Search term,Campaign,Ad group,Keyword,Match type,Cost,Clicks,Impressions,Date,Currency
"roof leak repair","Roofing","Emergency","roof leak",Broad,"50.00",5,50,2026-10-01,USD
"roof leak repair","Roofing","Emergency","[roof leak repair]",Exact,"40.00",4,40,2026-10-01,USD
"""
    obs, warnings = parse_search_terms_csv(csv_text)
    # Both distinct keyword segment rows must be preserved, not falsely dropped
    assert len(obs) == 2
    assert obs[0].triggering_keyword == "roof leak"
    assert obs[0].cost_micros == 50_000_000
    assert obs[1].triggering_keyword == "[roof leak repair]"
    assert obs[1].cost_micros == 40_000_000
    assert not any("Duplicate observation" in w for w in warnings)


def test_structured_quarantine_tracking() -> None:
    corrupt_csv = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"valid query","Roofing","50.00",5,50,2026-10-01,USD
"bad clicks","Roofing","50.00",50,5,2026-10-01,USD
"missing date","Roofing","50.00",5,50,,USD
"""
    quarantined: list[QuarantinedRow] = []
    obs, warnings = parse_search_terms_csv(corrupt_csv, quarantined_out=quarantined)

    assert len(obs) == 1
    assert len(quarantined) == 2
    assert quarantined[0].search_term_or_campaign == "bad clicks"
    assert "Clicks (50) exceeds impressions (5)" in quarantined[0].reason
    assert quarantined[1].search_term_or_campaign == "missing date"
    assert "Missing required observation date" in quarantined[1].reason

    # Verify exportable dictionary format
    dict_repr = quarantined[0].to_dict()
    assert "Row #" in dict_repr
    assert "Quarantine Reason" in dict_repr
    assert "Raw Values" in dict_repr


def test_non_search_network_quarantined_from_scope() -> None:
    mixed_csv = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency,Network
"search query","Roofing","50.00",5,50,2026-10-01,USD,SEARCH
"display query","Roofing","30.00",3,30,2026-10-01,USD,DISPLAY
"""
    quarantined: list[QuarantinedRow] = []
    obs, warnings = parse_search_terms_csv(mixed_csv, quarantined_out=quarantined)

    # Only the SEARCH network row is accepted
    assert len(obs) == 1
    assert obs[0].search_term == "search query"
    # Display row is quarantined from Search spend scope
    assert len(quarantined) == 1
    assert quarantined[0].search_term_or_campaign == "display query"
    assert "DISPLAY" in quarantined[0].reason


def test_date_reconciliation_tracks_excluded_rows_in_quarantine() -> None:
    st_csv = """Search term,Cost,Currency,Date,Network
query 1,50.00,USD,2026-10-01,SEARCH
query 2,50.00,USD,2026-10-05,SEARCH
"""
    cs_csv = """Campaign,Cost,Currency,Date,Network
camp 1,500.00,USD,2026-10-05,SEARCH
camp 1,500.00,USD,2026-10-10,SEARCH
"""
    quarantined: list[QuarantinedRow] = []
    st_obs, _ = parse_search_terms_csv(st_csv, quarantined_out=quarantined)
    cs_obs, _ = parse_campaign_spend_csv(cs_csv, quarantined_out=quarantined)

    report = validate_compatibility(st_obs, cs_obs, quarantined_out=quarantined)
    assert report.is_compatible is True
    assert report.has_date_reconciliation is True
    # Rows outside Oct 5 (common period is Oct 5..Oct 5) must be logged in quarantined_records
    outside_rows = [q for q in report.quarantined_records if "outside verified common period" in q.reason]
    assert len(outside_rows) == 2  # query 1 (Oct 1) and camp 1 (Oct 10)


def test_utf16_encoded_csv_support() -> None:
    csv_text = "Search term,Campaign,Cost,Clicks,Impressions,Date,Currency\nroofing,Camp,100.00,10,100,2026-10-01,USD\n"
    utf16_bytes = csv_text.encode("utf-16")
    obs, warnings = parse_search_terms_csv(utf16_bytes)
    assert len(obs) == 1
    assert obs[0].search_term == "roofing"
    assert obs[0].cost_micros == 100_000_000


def test_deduplication_missing_columns_distinct_traffic_preserved() -> None:
    # When disambiguating columns (match type, keyword, ad group, campaign ID) are missing,
    # differing metrics indicate distinct traffic segments (e.g. multi-keyword or device segments).
    csv_text = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"commercial roofing","Roofing Search","50.00",5,50,2026-10-01,USD
"commercial roofing","Roofing Search","30.00",3,30,2026-10-01,USD
"""
    obs, warnings = parse_search_terms_csv(csv_text)
    # Legitimate observations must NOT be discarded: both rows must be preserved
    assert len(obs) == 2
    assert obs[0].cost_micros == 50_000_000
    assert obs[1].cost_micros == 30_000_000
    total_spend = sum(o.cost_micros for o in obs)
    assert total_spend == 80_000_000
    assert any("Additional distinct traffic segment" in w for w in warnings)


def test_deduplication_missing_columns_exact_duplicate_skipped() -> None:
    # When metrics are identical, the row is an unambiguous duplicate and is skipped
    csv_text = """Search term,Campaign,Cost,Clicks,Impressions,Date,Currency
"commercial roofing","Roofing Search","50.00",5,50,2026-10-01,USD
"commercial roofing","Roofing Search","50.00",5,50,2026-10-01,USD
"""
    quarantined: list[QuarantinedRow] = []
    obs, warnings = parse_search_terms_csv(csv_text, quarantined_out=quarantined)
    assert len(obs) == 1
    assert obs[0].cost_micros == 50_000_000
    assert len(quarantined) == 1
    assert "Exact duplicate observation" in quarantined[0].reason


def test_deduplication_fully_segmented_ambiguous_duplicate_quarantined() -> None:
    # When all segment columns are explicitly specified and identical, conflicting metrics are ambiguous
    csv_text = """Search term,Campaign,Campaign ID,Ad Group,Ad Group ID,Keyword,Match type,Cost,Clicks,Impressions,Date,Currency
"roof repair","Camp 1","c_101","AdGroup 1","ag_201","roof repair","EXACT","50.00",5,50,2026-10-01,USD
"roof repair","Camp 1","c_101","AdGroup 1","ag_201","roof repair","EXACT","30.00",3,30,2026-10-01,USD
"""
    quarantined: list[QuarantinedRow] = []
    obs, warnings = parse_search_terms_csv(csv_text, quarantined_out=quarantined)
    # Row 1 is accepted, Row 2 is quarantined as an ambiguous duplicate
    assert len(obs) == 1
    assert obs[0].cost_micros == 50_000_000
    assert len(quarantined) == 1
    assert "Ambiguous duplicate" in quarantined[0].reason


def test_deduplication_campaign_spend_missing_id_preserves_distinct_segments() -> None:
    csv_text = """Campaign,Cost,Date,Currency,Network
"Search - Roofing",500.00,2026-10-01,USD,SEARCH
"Search - Roofing",300.00,2026-10-01,USD,SEARCH
"""
    obs, warnings = parse_campaign_spend_csv(csv_text)
    # Both distinct segments preserved without undercounting denominator
    assert len(obs) == 2
    assert sum(o.cost_micros for o in obs) == 800_000_000


def test_monetary_parsing_usd_eur_gbp_formats() -> None:
    # USD
    assert parse_money_to_micros("$1,234.56") == 1_234_560_000
    assert parse_money_to_micros("1,234.56 USD") == 1_234_560_000
    # GBP
    assert parse_money_to_micros("£1,234.56") == 1_234_560_000
    assert parse_money_to_micros("1,234.56 GBP") == 1_234_560_000
    # EUR
    assert parse_money_to_micros("1.234,56 €") == 1_234_560_000
    assert parse_money_to_micros("€ 1 234,56") == 1_234_560_000
    assert parse_money_to_micros("50,00 €") == 50_000_000
    assert parse_money_to_micros("50,00 EUR") == 50_000_000


def test_monetary_parsing_distinguishes_zero_missing_unavailable_and_invalid() -> None:
    # Genuine zero
    assert parse_money_to_micros("0") == 0
    assert parse_money_to_micros("0.00") == 0
    assert parse_money_to_micros("0,00") == 0
    # Missing
    assert parse_money_to_micros("") == 0
    assert parse_money_to_micros(None) == 0
    # Unavailable (Google Ads null indicators)
    assert parse_money_to_micros("--") == 0
    assert parse_money_to_micros("-") == 0
    assert parse_money_to_micros("N/A") == 0
    assert parse_money_to_micros("null") == 0
    # Negative values rejected
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("-50.00")
    # Invalid characters / corrupt data rejected (never converted to 0)
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("corrupt_value")
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("$$$")


def test_reject_ambiguous_numeric_formats() -> None:
    # Multiple decimal points
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("12.34.56")
    # Multiple commas with non-thousands grouping
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("12,34,56")
    # Conflicting punctuation
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("1,2.3,4")
    # Ambiguous malformed thousands
    with pytest.raises(CSVValidationError):
        parse_money_to_micros("1,2,3")


def test_unparseable_metrics_quarantined_not_converted_to_zero() -> None:
    # Ensure unparseable values in metrics are quarantined, never silently converted to zero
    bad_metrics_csv = """Search term,Campaign,Cost,Clicks,Impressions,Conversions,Date,Currency
"valid query","Camp","50.00",5,50,1.0,2026-10-01,USD
"corrupt conv query","Camp","50.00",5,50,INVALID_CONVERSIONS,2026-10-01,USD
"corrupt click query","Camp","50.00",BAD_CLICKS,50,0.0,2026-10-01,USD
"""
    quarantined: list[QuarantinedRow] = []
    obs, warnings = parse_search_terms_csv(bad_metrics_csv, quarantined_out=quarantined)

    # Only the first valid query should be accepted
    assert len(obs) == 1
    assert obs[0].search_term == "valid query"
    # Both corrupt rows must be quarantined
    assert len(quarantined) == 2
    assert quarantined[0].search_term_or_campaign == "corrupt conv query"
    assert "conversions" in quarantined[0].reason.lower()
    assert quarantined[1].search_term_or_campaign == "corrupt click query"
    assert "clicks" in quarantined[1].reason.lower()

