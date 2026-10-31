from __future__ import annotations

from datetime import date


ALLOWED_NETWORKS = ("SEARCH", "SEARCH_PARTNERS")


def _iso(d: date) -> str:
    if not isinstance(d, date):
        raise TypeError("date arguments must be datetime.date")
    return d.isoformat()


def _validate_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start date must be <= end date")


def search_term_query(start: date, end: date) -> str:
    """GAQL for daily Search campaign query observations.

    Daily segmentation is intentional: it lets the accuracy layer treat recent rows
    as conversion-immature instead of contaminating the historical evidence.
    """

    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.advertising_channel_type,
  ad_group.id,
  ad_group.name,
  search_term_view.search_term,
  search_term_view.status,
  segments.date,
  segments.ad_network_type,
  segments.search_term_match_source,
  segments.search_term_match_type,
  segments.search_term_targeting_status,
  segments.keyword.info.text,
  segments.keyword.info.match_type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.all_conversions,
  metrics.all_conversions_value
FROM search_term_view
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def campaign_network_spend_query(start: date, end: date) -> str:
    """Denominator query for search-term visibility/coverage calculation."""

    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.advertising_channel_type,
  segments.date,
  segments.ad_network_type,
  metrics.cost_micros
FROM campaign
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def campaign_negative_keywords_query() -> str:
    return """
SELECT
  campaign.id,
  campaign_criterion.resource_name,
  campaign_criterion.negative,
  campaign_criterion.type,
  campaign_criterion.keyword.text,
  campaign_criterion.keyword.match_type
FROM campaign_criterion
WHERE campaign_criterion.negative = TRUE
  AND campaign_criterion.type = 'KEYWORD'
""".strip()


def ad_group_negative_keywords_query() -> str:
    return """
SELECT
  campaign.id,
  ad_group.id,
  ad_group_criterion.resource_name,
  ad_group_criterion.negative,
  ad_group_criterion.type,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type
FROM ad_group_criterion
WHERE ad_group_criterion.negative = TRUE
  AND ad_group_criterion.type = 'KEYWORD'
""".strip()


def shared_negative_sets_query() -> str:
    """Find shared negative keyword sets attached to campaigns.

    The set contents are fetched separately from `shared_criterion`; keeping this as
    a separate query makes attachment scope explicit and auditable.
    """

    return """
SELECT
  campaign.id,
  campaign_shared_set.resource_name,
  campaign_shared_set.shared_set,
  shared_set.id,
  shared_set.name,
  shared_set.type
FROM campaign_shared_set
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
""".strip()


def shared_negative_keywords_query() -> str:
    return """
SELECT
  shared_set.id,
  shared_set.name,
  shared_set.type,
  shared_criterion.resource_name,
  shared_criterion.keyword.text,
  shared_criterion.keyword.match_type
FROM shared_criterion
WHERE shared_set.type IN ('NEGATIVE_KEYWORDS', 'ACCOUNT_LEVEL_NEGATIVE_KEYWORDS')
""".strip()


def account_negative_keyword_list_query() -> str:
    return """
SELECT
  customer_negative_criterion.resource_name,
  customer_negative_criterion.type,
  customer_negative_criterion.negative_keyword_list.shared_set
FROM customer_negative_criterion
WHERE customer_negative_criterion.type = 'NEGATIVE_KEYWORD_LIST'
""".strip()
