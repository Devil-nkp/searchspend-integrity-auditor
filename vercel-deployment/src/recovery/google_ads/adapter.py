from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Iterator, Mapping, Protocol

from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.google_ads.gaql import campaign_network_spend_query, search_term_query

GOOGLE_ADS_API_VERSION = "v26"


class AdsSearchService(Protocol):
    def search_stream(self, *, customer_id: str, query: str) -> Iterable[Any]: ...


@dataclass(slots=True)
class GoogleAdsV26Adapter:
    """Thin version-specific adapter.

    Domain/scoring code never imports Google's generated protobuf types. This keeps
    future API migrations localized to this file and the GAQL definitions.
    """

    client: Any

    @classmethod
    def from_google_ads_client(cls, client: Any) -> "GoogleAdsV26Adapter":
        return cls(client=client)

    def _service(self) -> AdsSearchService:
        return self.client.get_service(
            "GoogleAdsService", version=GOOGLE_ADS_API_VERSION
        )

    @staticmethod
    def _enum_name(value: Any) -> str:
        # Proto-plus enum values stringify differently across generated versions.
        # Prefer the enum name when available; fallback to stable string conversion.
        name = getattr(value, "name", None)
        if name:
            return str(name)
        text = str(value)
        return text.rsplit(".", 1)[-1]

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        # Decimal(str(...)) avoids binary-float artifacts from protobuf doubles.
        return Decimal(str(value))

    def iter_search_terms(
        self, customer_id: str, start: date, end: date
    ) -> Iterator[SearchTermObservation]:
        query = search_term_query(start, end)
        stream = self._service().search_stream(customer_id=customer_id, query=query)

        for batch in stream:
            for row in batch.results:
                kw_text = getattr(row.segments.keyword.info, "text", "") or None
                kw_match = getattr(row.segments.keyword.info, "match_type", None)
                yield SearchTermObservation(
                    customer_id=str(row.customer.id),
                    campaign_id=str(row.campaign.id),
                    campaign_name=str(row.campaign.name),
                    ad_group_id=str(row.ad_group.id),
                    ad_group_name=str(row.ad_group.name),
                    search_term=str(row.search_term_view.search_term),
                    date=date.fromisoformat(str(row.segments.date)),
                    network=self._enum_name(row.segments.ad_network_type),
                    match_source=self._enum_name(row.segments.search_term_match_source),
                    search_term_match_type=self._enum_name(
                        row.segments.search_term_match_type
                    ),
                    targeting_status=self._enum_name(
                        row.segments.search_term_targeting_status
                    ),
                    triggering_keyword=kw_text,
                    triggering_keyword_match_type=(
                        self._enum_name(kw_match) if kw_text is not None else None
                    ),
                    impressions=int(row.metrics.impressions),
                    clicks=int(row.metrics.clicks),
                    cost_micros=int(row.metrics.cost_micros),
                    conversions=self._decimal(row.metrics.conversions),
                    conversions_value=self._decimal(row.metrics.conversions_value),
                    all_conversions=self._decimal(row.metrics.all_conversions),
                    all_conversions_value=self._decimal(
                        row.metrics.all_conversions_value
                    ),
                    currency_code=str(row.customer.currency_code),
                )

    def iter_campaign_network_spend(
        self, customer_id: str, start: date, end: date
    ) -> Iterator[CampaignSpendObservation]:
        query = campaign_network_spend_query(start, end)
        stream = self._service().search_stream(customer_id=customer_id, query=query)

        for batch in stream:
            for row in batch.results:
                yield CampaignSpendObservation(
                    customer_id=str(row.customer.id),
                    campaign_id=str(row.campaign.id),
                    campaign_name=str(row.campaign.name),
                    date=date.fromisoformat(str(row.segments.date)),
                    network=self._enum_name(row.segments.ad_network_type),
                    cost_micros=int(row.metrics.cost_micros),
                    currency_code=str(row.customer.currency_code),
                )
