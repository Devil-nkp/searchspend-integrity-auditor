from datetime import date

from recovery.google_ads.gaql import campaign_network_spend_query, search_term_query


def test_search_term_query_is_scoped_to_search_campaigns_and_networks() -> None:
    q = search_term_query(date(2026, 8, 1), date(2026, 10, 1))
    assert "campaign.advertising_channel_type = 'SEARCH'" in q
    assert "'SEARCH_PARTNERS'" in q
    assert "segments.date" in q
    assert "metrics.cost_micros" in q
    assert "segments.search_term_targeting_status" in q


def test_campaign_query_uses_same_date_and_network_scope() -> None:
    q = campaign_network_spend_query(date(2026, 8, 1), date(2026, 10, 1))
    assert "campaign.advertising_channel_type = 'SEARCH'" in q
    assert "segments.ad_network_type" in q
    assert "2026-08-01" in q
    assert "2026-10-01" in q
