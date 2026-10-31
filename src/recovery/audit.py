from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from recovery.accuracy import AccuracyPolicy
from recovery.domain import (
    CoverageBand,
    CoverageSummary,
    DataMaturity,
    FindingConfidence,
    Money,
    SearchTermObservation,
)


@dataclass(frozen=True, slots=True)
class AuditRow:
    search_term: str
    campaign: str
    ad_group: str
    observation_date: date
    clicks: int
    impressions: int
    ctr_percent: Decimal
    spend_micros: int
    spend_formatted: str
    conversions: Decimal
    conversions_value: Decimal
    currency_code: str
    maturity_status: DataMaturity
    confidence_status: FindingConfidence
    zero_conv_waste_allowed: bool
    status_label: str
    explanation: str
    is_synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "Search Term": self.search_term,
            "Campaign": self.campaign,
            "Ad Group": self.ad_group,
            "Observation Date": self.observation_date.isoformat(),
            "Maturity": self.maturity_status.value.upper(),
            "Confidence": self.confidence_status.value.upper(),
            "Spend": self.spend_formatted,
            "Clicks": self.clicks,
            "Impressions": self.impressions,
            "CTR (%)": float(self.ctr_percent),
            "Conversions": float(self.conversions),
            "Status": self.status_label,
            "Integrity Explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class AuditSummary:
    total_observations: int
    total_spend_micros: int
    mature_count: int
    mature_spend_micros: int
    immature_count: int
    immature_spend_micros: int
    zero_conv_count: int
    zero_conv_spend_micros: int
    converting_count: int
    converting_spend_micros: int
    currency_code: str
    as_of: date
    conversion_lag_days: int
    coverage_summary: CoverageSummary
    rows: list[AuditRow] = field(default_factory=list)
    lag_quarantine_count: int = 0
    lag_quarantine_spend_micros: int = 0
    post_audit_count: int = 0
    post_audit_spend_micros: int = 0

    @property
    def total_spend(self) -> Money:
        return Money(self.total_spend_micros, self.currency_code)

    @property
    def mature_spend(self) -> Money:
        return Money(self.mature_spend_micros, self.currency_code)

    @property
    def immature_spend(self) -> Money:
        return Money(self.immature_spend_micros, self.currency_code)

    @property
    def lag_quarantine_spend(self) -> Money:
        return Money(self.lag_quarantine_spend_micros, self.currency_code)

    @property
    def post_audit_spend(self) -> Money:
        return Money(self.post_audit_spend_micros, self.currency_code)

    @property
    def zero_conv_spend(self) -> Money:
        return Money(self.zero_conv_spend_micros, self.currency_code)

    @property
    def converting_spend(self) -> Money:
        return Money(self.converting_spend_micros, self.currency_code)

    @property
    def is_mature_partition_valid(self) -> bool:
        """Verify that mature converting spend plus mature zero-conversion spend equals mature spend."""
        return (self.converting_spend_micros + self.zero_conv_spend_micros) == self.mature_spend_micros

    @property
    def is_spend_partition_valid(self) -> bool:
        """Verify that mature spend plus immature spend equals visible search-term spend."""
        return (self.mature_spend_micros + self.immature_spend_micros) == self.total_spend_micros

    @property
    def is_immature_subpartition_valid(self) -> bool:
        """Verify that lag quarantine spend plus post-audit spend equals immature spend."""
        return (self.lag_quarantine_spend_micros + self.post_audit_spend_micros) == self.immature_spend_micros


def run_audit(
    search_terms: Sequence[SearchTermObservation],
    coverage_summary: CoverageSummary,
    policy: AccuracyPolicy,
    as_of: date,
    business_context_confirmed: bool = False,
    semantic_scores: Mapping[str, Decimal] | None = None,
    existing_exclusions: set[str] | None = None,
    is_synthetic: bool = False,
) -> AuditSummary:
    """Generate an integrity audit for search terms respecting the Accuracy Contract."""
    semantic_map = semantic_scores or {}
    exclusions = {e.lower().strip() for e in (existing_exclusions or set())}

    rows: list[AuditRow] = []

    total_micros = 0
    mature_micros = 0
    immature_micros = 0
    lag_quarantine_micros = 0
    post_audit_micros = 0
    zero_conv_micros = 0
    converting_micros = 0
    mature_count = 0
    immature_count = 0
    lag_quarantine_count = 0
    post_audit_count = 0
    zero_conv_count = 0
    converting_count = 0

    curr_code = coverage_summary.currency_code

    for obs in search_terms:
        total_micros += obs.cost_micros
        obs_curr = obs.currency_code
        if obs_curr != curr_code:
            curr_code = obs_curr

        maturity = policy.maturity(obs.date, as_of)
        zero_waste_proof_allowed = policy.can_use_zero_conversion_as_waste_proof(
            observation_date=obs.date, as_of=as_of
        )

        term_lower = obs.search_term.lower().strip()
        already_excluded = term_lower in exclusions

        # Semantic confidence check:
        # If semantic score is supplied externally, use it. Otherwise, note that semantic classifier is deferred.
        has_semantic = term_lower in semantic_map
        sem_score = semantic_map.get(term_lower, Decimal("0.0"))

        if has_semantic:
            confidence = policy.confidence_for_semantic_mismatch(
                semantic_confidence=sem_score,
                business_context_confirmed=business_context_confirmed,
                coverage_band=coverage_summary.band,
                already_excluded=already_excluded,
            )
        else:
            # Without external input or Phase 2 classifier, finding confidence cannot be asserted
            confidence = FindingConfidence.INSUFFICIENT

        # Calculate CTR
        if obs.impressions > 0:
            ctr = (Decimal(obs.clicks) / Decimal(obs.impressions) * Decimal("100")).quantize(
                Decimal("0.01")
            )
        else:
            ctr = Decimal("0.00")

        # Determine explanation
        if maturity == DataMaturity.POST_AUDIT:
            immature_count += 1
            immature_micros += obs.cost_micros
            post_audit_count += 1
            post_audit_micros += obs.cost_micros
            status_label = "Post-Audit Date (Quarantine)"
            days_future = (obs.date - as_of).days
            explanation = (
                f"Observed on {obs.date.isoformat()}, which is {days_future} day(s) after audit reference date {as_of.isoformat()}. "
                "Post-audit observation strictly post-dates audit cutoff; cannot contribute to retrospective waste claims."
            )
        elif maturity == DataMaturity.IMMATURE:
            immature_count += 1
            immature_micros += obs.cost_micros
            lag_quarantine_count += 1
            lag_quarantine_micros += obs.cost_micros
            status_label = "Immature (Lag Quarantine)"
            days_ago = (as_of - obs.date).days
            explanation = (
                f"Observed {days_ago} day(s) prior to audit date {as_of.isoformat()}. "
                f"Within the {policy.conversion_lag_days}-day conversion-lag window. "
                "Attribution is not mature; premature waste penalties are strictly blocked."
            )
        else:
            mature_count += 1
            mature_micros += obs.cost_micros
            if obs.conversions > 0:
                converting_count += 1
                converting_micros += obs.cost_micros
                status_label = "Mature (Converting)"
                explanation = (
                    f"Mature observation ({obs.conversions} conversions recorded). "
                    "Demonstrated commercial intent."
                )
            else:
                zero_conv_count += 1
                zero_conv_micros += obs.cost_micros
                status_label = "Mature (Zero Conv)"
                if already_excluded:
                    explanation = (
                        "Already present in existing negative keyword exclusions. "
                        "No new action required."
                    )
                elif not business_context_confirmed:
                    explanation = (
                        f"Zero recorded conversions after {policy.conversion_lag_days}-day lag window. "
                        "Contextual note: Zero conversions alone cannot prove waste (untracked phone calls, multi-touch research assists, or sample size). "
                        "Requires verified advertiser business-context confirmation before any negative recommendation."
                    )
                elif confidence == FindingConfidence.HIGH:
                    explanation = (
                        "High semantic mismatch confirmed against business profile with high account coverage. "
                        "Eligible for manual negative keyword review."
                    )
                elif confidence == FindingConfidence.MEDIUM:
                    explanation = (
                        "Semantic mismatch indicated, but account coverage is below 80%. "
                        "Confidence capped at MEDIUM due to hidden query volume."
                    )
                else:
                    explanation = (
                        "Zero conversions observed. Semantic mismatch score below threshold (0.95). "
                        "Cannot safely claim spend was avoidable."
                    )

        row = AuditRow(
            search_term=obs.search_term,
            campaign=obs.campaign_name,
            ad_group=obs.ad_group_name,
            observation_date=obs.date,
            clicks=obs.clicks,
            impressions=obs.impressions,
            ctr_percent=ctr,
            spend_micros=obs.cost_micros,
            spend_formatted=obs.cost.format(),
            conversions=obs.conversions,
            conversions_value=obs.conversions_value,
            currency_code=obs.currency_code,
            maturity_status=maturity,
            confidence_status=confidence,
            zero_conv_waste_allowed=zero_waste_proof_allowed,
            status_label=status_label,
            explanation=explanation,
            is_synthetic=is_synthetic,
        )
        rows.append(row)

    return AuditSummary(
        total_observations=len(rows),
        total_spend_micros=total_micros,
        mature_count=mature_count,
        mature_spend_micros=mature_micros,
        immature_count=immature_count,
        immature_spend_micros=immature_micros,
        zero_conv_count=zero_conv_count,
        zero_conv_spend_micros=zero_conv_micros,
        converting_count=converting_count,
        converting_spend_micros=converting_micros,
        currency_code=curr_code,
        as_of=as_of,
        conversion_lag_days=policy.conversion_lag_days,
        coverage_summary=coverage_summary,
        rows=rows,
        lag_quarantine_count=lag_quarantine_count,
        lag_quarantine_spend_micros=lag_quarantine_micros,
        post_audit_count=post_audit_count,
        post_audit_spend_micros=post_audit_micros,
    )
