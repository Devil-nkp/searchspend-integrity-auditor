from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from recovery.domain import (
    CampaignSpendObservation,
    CoverageBand,
    CoverageSummary,
    Money,
    SearchTermObservation,
    summarize_coverage,
)

MICROS_PER_UNIT = Decimal("1000000")
ALLOWED_NETWORKS = {"SEARCH", "SEARCH_PARTNERS"}

# Flexible header mapping aliases (case-insensitive, normalized)
SEARCH_TERMS_ALIASES: dict[str, Sequence[str]] = {
    "search_term": (
        "search term",
        "search_term",
        "query",
        "search query",
        "customer search term",
    ),
    "campaign_name": (
        "campaign",
        "campaign name",
        "campaign_name",
        "campaigns",
    ),
    "campaign_id": (
        "campaign id",
        "campaign_id",
    ),
    "ad_group_name": (
        "ad group",
        "ad group name",
        "ad_group",
        "ad_group_name",
    ),
    "ad_group_id": (
        "ad group id",
        "ad_group_id",
    ),
    "date": (
        "date",
        "day",
        "segments.date",
        "observation date",
    ),
    "network": (
        "network",
        "network (with search partners)",
        "ad network type",
        "network type",
        "segments.ad_network_type",
    ),
    "cost": (
        "cost",
        "spend",
        "cost micros",
        "cost_micros",
        "metrics.cost_micros",
    ),
    "impressions": (
        "impressions",
        "impr.",
        "impr",
        "metrics.impressions",
    ),
    "clicks": (
        "clicks",
        "metrics.clicks",
    ),
    "conversions": (
        "conversions",
        "conv.",
        "conv",
        "metrics.conversions",
    ),
    "conversions_value": (
        "conv. value",
        "conversion value",
        "conversions value",
        "metrics.conversions_value",
    ),
    "currency_code": (
        "currency",
        "currency code",
        "customer.currency_code",
    ),
    "match_type": (
        "match type",
        "search term match type",
        "segments.search_term_match_type",
    ),
    "triggering_keyword": (
        "keyword",
        "triggering keyword",
        "segments.keyword.info.text",
    ),
}

CAMPAIGN_SPEND_ALIASES: dict[str, Sequence[str]] = {
    "campaign_name": (
        "campaign",
        "campaign name",
        "campaign_name",
    ),
    "campaign_id": (
        "campaign id",
        "campaign_id",
    ),
    "date": (
        "date",
        "day",
        "segments.date",
    ),
    "network": (
        "network",
        "network (with search partners)",
        "ad network type",
        "segments.ad_network_type",
    ),
    "cost": (
        "cost",
        "spend",
        "cost micros",
        "cost_micros",
        "metrics.cost_micros",
    ),
    "currency_code": (
        "currency",
        "currency code",
        "customer.currency_code",
    ),
}


class CSVValidationError(ValueError):
    """Raised when CSV structure, types, or business constraints are violated."""


def normalize_header(header: str) -> str:
    """Normalize headers for case/space/punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", str(header).strip().lower())


def _strip_metadata_header_lines(text: str, target_keywords: Sequence[str]) -> str:
    """Find the true CSV header line in real-world exports that contain metadata or report title lines."""
    lines = text.splitlines()
    if not lines:
        return text

    target_norms = {normalize_header(k) for k in target_keywords}

    for idx, line in enumerate(lines[:20]):
        try:
            row_items = next(csv.reader([line]))
        except Exception:
            continue
        row_norms = {normalize_header(item) for item in row_items if item}
        if any(tk in row_norms for tk in target_norms):
            return "\n".join(lines[idx:])

    return text


def parse_financial_decimal(
    value: Any,
    field_name: str = "metric",
    allow_negative: bool = False,
) -> Decimal:
    """Parse financial and numerical metrics across USD, EUR, and GBP formatting standards.

    Preserves integer-micros and Decimal precision without floating-point arithmetic.
    Distinguishes genuine zero ("0", "0.00", "0,00"), missing ("", None),
    and Google Ads standard unavailable representations ("--", "-", "N/A", "null").

    Rejects negative values for non-negative Google Ads metrics, binary floats,
    ambiguous punctuation (conflicting decimal/thousands separators), and unparseable non-numeric text.
    Never silently converts an unparseable or corrupt value into zero.
    """
    if isinstance(value, float):
        raise TypeError(f"Binary float is prohibited for financial parsing of {field_name}; use str or Decimal")

    if value is None:
        return Decimal("0")

    if isinstance(value, (int, Decimal)):
        if not allow_negative and value < 0:
            raise CSVValidationError(f"Negative values prohibited for {field_name}: '{value}'")
        return Decimal(str(value))

    val_str = str(value).strip()
    if not val_str or set(val_str) <= {"-"} or val_str in ("N/A", "na", "null", "None", "none"):
        return Decimal("0")

    # Reject leading or contained negative sign if negative values are not allowed
    if ("-" in val_str) and not allow_negative:
        raise CSVValidationError(f"Negative values prohibited for {field_name}: '{value}'")

    # Strip recognized currency symbols: $, €, £, ₹, ¥
    s = re.sub(r"[\$€£₹¥]", "", val_str).strip()

    # Strip optional 3-letter currency code prefix or suffix (e.g. "USD", "EUR", "GBP")
    s = re.sub(r"^(USD|EUR|GBP|INR|CAD|AUD)\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s*(USD|EUR|GBP|INR|CAD|AUD)$", "", s, flags=re.IGNORECASE).strip()

    if not s or set(s) <= {"-"} or s in ("N/A", "na", "null", "None", "none"):
        # If the string had text with currency symbols but no digits or dashes (e.g. '$$$'), reject
        if val_str and not (set(val_str) <= {"-"}) and not any(ch.isdigit() for ch in val_str):
            raise CSVValidationError(f"Missing numeric digits in {field_name}: '{value}'")
        return Decimal("0")

    # Reject invalid characters (only digits, spaces, dots, commas allowed)
    if re.search(r"[^\d., ]", s):
        raise CSVValidationError(f"Invalid non-numeric characters in {field_name}: '{value}'")

    # Remove space thousands separators (e.g. "1 234,56" or "1 234.56")
    s = s.replace(" ", "")

    num_dots = s.count(".")
    num_commas = s.count(",")

    if num_dots > 0 and num_commas > 0:
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma < last_dot:
            # US/UK style: e.g. 1,234.56 or 1,234,567.89
            if num_dots > 1:
                raise CSVValidationError(f"Multiple decimal points in {field_name}: '{value}'")
            parts = s[:last_dot].split(",")
            for part in parts[1:]:
                if len(part) != 3:
                    raise CSVValidationError(f"Malformed thousands separator in {field_name}: '{value}'")
            cleaned = s.replace(",", "")
        else:
            # European style: e.g. 1.234,56 or 1.234.567,89
            if num_commas > 1:
                raise CSVValidationError(f"Multiple decimal commas in {field_name}: '{value}'")
            parts = s[:last_comma].split(".")
            for part in parts[1:]:
                if len(part) != 3:
                    raise CSVValidationError(f"Malformed thousands separator in {field_name}: '{value}'")
            cleaned = s.replace(".", "").replace(",", ".")
    elif num_dots > 1:
        # Multiple dots without commas. E.g. 1.234.567 (European thousands)
        parts = s.split(".")
        for part in parts[1:]:
            if len(part) != 3:
                raise CSVValidationError(f"Ambiguous multiple periods in {field_name}: '{value}'")
        cleaned = s.replace(".", "")
    elif num_commas > 1:
        # Multiple commas without dots. E.g. 1,234,567 (US thousands)
        parts = s.split(",")
        for part in parts[1:]:
            if len(part) != 3:
                raise CSVValidationError(f"Ambiguous multiple commas in {field_name}: '{value}'")
        cleaned = s.replace(",", "")
    elif num_commas == 1 and num_dots == 0:
        comma_idx = s.find(",")
        after_comma = s[comma_idx + 1:]
        if len(after_comma) in (1, 2):
            # European decimal comma: e.g. "50,00" -> "50.00"
            cleaned = s.replace(",", ".")
        elif len(after_comma) == 3:
            # Thousands separator: e.g. "1,250" -> "1250"
            cleaned = s.replace(",", "")
        else:
            raise CSVValidationError(f"Ambiguous comma formatting in {field_name}: '{value}'")
    elif num_dots == 1 and num_commas == 0:
        cleaned = s
    else:
        cleaned = s

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise CSVValidationError(f"Unparseable numeric value for {field_name}: '{value}'") from exc


def parse_money_to_micros(value: Any, is_already_micros: bool = False) -> int:
    """Convert monetary input to integer micros without floating point arithmetic."""
    dec = parse_financial_decimal(value, field_name="Cost", allow_negative=False)
    if is_already_micros:
        return int(dec)
    micros_dec = dec * MICROS_PER_UNIT
    return int(micros_dec)


def parse_integer_metric(value: Any, field_name: str = "metric") -> int:
    """Parse integer metrics (clicks, impressions), rejecting unparseable or negative data."""
    dec = parse_financial_decimal(value, field_name=field_name, allow_negative=False)
    return int(dec)


def parse_decimal_metric(value: Any, field_name: str = "metric") -> Decimal:
    """Parse decimal metrics (conversions, conversions value), rejecting unparseable or negative data."""
    return parse_financial_decimal(value, field_name=field_name, allow_negative=False)


def parse_date(value: Any) -> date:
    """Parse string or date into datetime.date."""
    if isinstance(value, date):
        return value

    val_str = str(value).strip()
    if not val_str:
        raise CSVValidationError("Date field cannot be empty")

    # Try common formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            continue

    try:
        return date.fromisoformat(val_str)
    except ValueError as exc:
        raise CSVValidationError(f"Unrecognized date format: '{val_str}'") from exc


def resolve_columns(
    raw_headers: Sequence[str],
    aliases: Mapping[str, Sequence[str]],
    custom_mapping: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Match CSV headers to canonical field names."""
    normalized_raw = {normalize_header(h): h for h in raw_headers}
    resolved: dict[str, str] = {}

    if custom_mapping:
        for canonical, user_col in custom_mapping.items():
            norm_user = normalize_header(user_col)
            if norm_user in normalized_raw:
                resolved[canonical] = normalized_raw[norm_user]

    for canonical, alias_list in aliases.items():
        if canonical in resolved:
            continue
        for alias in alias_list:
            norm_alias = normalize_header(alias)
            if norm_alias in normalized_raw:
                resolved[canonical] = normalized_raw[norm_alias]
                break

    return resolved


@dataclass(frozen=True, slots=True)
class QuarantinedRow:
    """Structured record of an invalid, non-search, or excluded row quarantined during ingestion."""

    row_number: int
    file_type: str  # "Search Terms" or "Campaign Spend"
    search_term_or_campaign: str
    reason: str
    raw_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "Row #": self.row_number,
            "Report File": self.file_type,
            "Search Term / Campaign": self.search_term_or_campaign,
            "Quarantine Reason": self.reason,
            "Raw Values": str(self.raw_data),
        }


@dataclass(slots=True)
class IngestionResult:
    search_terms: list[SearchTermObservation] = field(default_factory=list)
    campaign_spend: list[CampaignSpendObservation] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    quarantined_records: list[QuarantinedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_search_terms_csv(
    file_content: str | bytes,
    default_currency: str = "USD",
    custom_mapping: Mapping[str, str] | None = None,
    quarantined_out: list[QuarantinedRow] | None = None,
) -> tuple[list[SearchTermObservation], list[str]]:
    """Parse Google Ads Search Terms report CSV into domain SearchTermObservation records.

    Deduplication Policy:
    In Google Ads, an observation is identified by (date, campaign_id, ad_group_id, search_term,
    network, search_term_match_type, triggering_keyword). Distinct triggering keywords or match types
    for the same query on the same day are legitimate distinct traffic segments and are preserved.
    Identical observations matching all segment dimensions are deduplicated to prevent spend inflation.

    Metric Integrity Policy:
    Records where clicks > impressions are strictly quarantined without silent clamping.
    Records with missing or malformed dates are quarantined without automatic fallback.
    Non-search network records (Display, Video) are quarantined from Search spend scope.
    """
    if isinstance(file_content, bytes):
        try:
            text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_content.decode("utf-16", errors="replace")
    else:
        text = file_content

    # Strip title/metadata rows if present
    text = _strip_metadata_header_lines(
        text, ["search_term", "search term", "query", "customer search term"]
    )

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CSVValidationError("CSV file is empty or missing headers")

    col_map = resolve_columns(reader.fieldnames, SEARCH_TERMS_ALIASES, custom_mapping)

    # Validate essential fields
    if "search_term" not in col_map:
        raise CSVValidationError(
            "Missing required column for 'Search term'. Available columns: "
            + ", ".join(reader.fieldnames)
        )
    if "cost" not in col_map:
        raise CSVValidationError(
            "Missing required column for 'Cost'. Available columns: "
            + ", ".join(reader.fieldnames)
        )

    observations: list[SearchTermObservation] = []
    warnings: list[str] = []
    currencies_seen: set[str] = set()
    seen_row_dict: dict[tuple[date, str, str, str, str, str, str], list[tuple[int, int, int, Decimal, Decimal]]] = {}

    has_match_type_col = "match_type" in col_map
    has_kw_col = "triggering_keyword" in col_map
    has_campaign_id_col = "campaign_id" in col_map
    has_ad_group_id_col = "ad_group_id" in col_map
    is_fully_segmented = (
        has_match_type_col
        and has_kw_col
        and has_campaign_id_col
        and has_ad_group_id_col
    )

    is_micros_col = "micros" in col_map["cost"].lower()

    for row_idx, row in enumerate(reader, start=2):
        term_text = (row.get(col_map["search_term"]) or "").strip()
        if not term_text:
            warnings.append(f"Row {row_idx}: Skipped empty search term")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign="<empty>",
                        reason="Empty search term text",
                        raw_data=dict(row),
                    )
                )
            continue

        # Skip Google Ads summary totals at bottom of reports
        term_lower = term_text.lower()
        if (
            term_lower.startswith("total:")
            or term_lower == "total"
            or term_lower in ("total: account", "total: search terms", "account total")
        ):
            warnings.append(f"Row {row_idx}: Skipped Google Ads summary total row '{term_text}'")
            continue

        cost_val = row.get(col_map["cost"], "0")
        try:
            cost_micros = parse_money_to_micros(cost_val, is_already_micros=is_micros_col)
        except CSVValidationError:
            warnings.append(f"Row {row_idx}: Invalid cost '{cost_val}'; row quarantined.")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Invalid monetary cost value '{cost_val}'",
                        raw_data=dict(row),
                    )
                )
            continue

        raw_currency = (
            row.get(col_map.get("currency_code", ""))
            or default_currency
        ).strip().upper()
        if len(raw_currency) != 3 or not raw_currency.isalpha():
            raw_currency = default_currency.upper()
        currencies_seen.add(raw_currency)

        # 1. Date handling: Explicit row rejection/quarantine on malformed/missing dates (No fallback)
        date_col = col_map.get("date")
        raw_date_val = (row.get(date_col) or "").strip() if date_col else ""
        if not raw_date_val:
            warnings.append(
                f"Row {row_idx}: Missing required observation date for search term '{term_text}'; row quarantined."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason="Missing required observation date",
                        raw_data=dict(row),
                    )
                )
            continue
        try:
            obs_date = parse_date(raw_date_val)
        except CSVValidationError:
            warnings.append(
                f"Row {row_idx}: Malformed date '{raw_date_val}' for search term '{term_text}'; row quarantined."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Malformed date '{raw_date_val}'",
                        raw_data=dict(row),
                    )
                )
            continue

        network_col = col_map.get("network")
        raw_network = (row.get(network_col) or "SEARCH").strip().upper()
        if "PARTNER" in raw_network:
            norm_network = "SEARCH_PARTNERS"
        elif "SEARCH" in raw_network:
            norm_network = "SEARCH"
        else:
            norm_network = raw_network

        if norm_network not in ALLOWED_NETWORKS:
            warnings.append(
                f"Row {row_idx}: Non-search network '{raw_network}' observed for '{term_text}'; "
                "row quarantined from Search spend scope."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Non-search network '{raw_network}' outside Search/Search Partners scope",
                        raw_data=dict(row),
                    )
                )
            continue

        impr_col = col_map.get("impressions")
        try:
            impressions = parse_integer_metric(
                row.get(impr_col, "0") if impr_col else "0", field_name="impressions"
            )
        except (CSVValidationError, TypeError) as exc:
            warnings.append(f"Row {row_idx}: Invalid impressions for '{term_text}'; row quarantined. ({exc})")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Invalid impressions metric: {exc}",
                        raw_data=dict(row),
                    )
                )
            continue

        clicks_col = col_map.get("clicks")
        try:
            clicks = parse_integer_metric(
                row.get(clicks_col, "0") if clicks_col else "0", field_name="clicks"
            )
        except (CSVValidationError, TypeError) as exc:
            warnings.append(f"Row {row_idx}: Invalid clicks for '{term_text}'; row quarantined. ({exc})")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Invalid clicks metric: {exc}",
                        raw_data=dict(row),
                    )
                )
            continue

        # 4. Metric integrity: Do NOT silently clamp clicks > impressions; quarantine invalid records
        if clicks > impressions:
            warnings.append(
                f"Row {row_idx}: Invalid metric integrity: clicks ({clicks}) exceeds impressions ({impressions}) "
                f"for search term '{term_text}'. Row quarantined to preserve source data integrity."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Clicks ({clicks}) exceeds impressions ({impressions})",
                        raw_data=dict(row),
                    )
                )
            continue

        conv_col = col_map.get("conversions")
        try:
            conversions = parse_decimal_metric(
                row.get(conv_col, "0") if conv_col else "0", field_name="conversions"
            )
        except (CSVValidationError, TypeError) as exc:
            warnings.append(f"Row {row_idx}: Invalid conversions for '{term_text}'; row quarantined. ({exc})")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Invalid conversions metric: {exc}",
                        raw_data=dict(row),
                    )
                )
            continue

        conv_val_col = col_map.get("conversions_value")
        try:
            conversions_value = parse_decimal_metric(
                row.get(conv_val_col, "0") if conv_val_col else "0", field_name="conversions_value"
            )
        except (CSVValidationError, TypeError) as exc:
            warnings.append(f"Row {row_idx}: Invalid conversions value for '{term_text}'; row quarantined. ({exc})")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Search Terms",
                        search_term_or_campaign=term_text,
                        reason=f"Invalid conversions_value metric: {exc}",
                        raw_data=dict(row),
                    )
                )
            continue

        campaign_name = (
            row.get(col_map.get("campaign_name", "")) or "Default Campaign"
        ).strip()
        campaign_id = (
            row.get(col_map.get("campaign_id", ""))
            or f"c_{normalize_header(campaign_name)}"
        ).strip()

        ad_group_name = (
            row.get(col_map.get("ad_group_name", "")) or "Default Ad Group"
        ).strip()
        ad_group_id = (
            row.get(col_map.get("ad_group_id", ""))
            or f"ag_{normalize_header(ad_group_name)}"
        ).strip()

        match_type = (row.get(col_map.get("match_type", "")) or "BROAD").strip().upper()
        kw_text = (row.get(col_map.get("triggering_keyword", "")) or "").strip() or None

        # 3. Deduplication Policy & Fallback Strategy:
        # Prevent duplicate observations from silently inflating spend while ensuring legitimate
        # unsegmented observations are not discarded.
        obs_key = (
            obs_date,
            campaign_id.lower(),
            ad_group_id.lower(),
            term_text.lower(),
            norm_network,
            match_type.lower(),
            (kw_text or "").lower(),
        )
        metrics_sig = (cost_micros, clicks, impressions, conversions, conversions_value)

        if obs_key in seen_row_dict:
            prior_metrics = seen_row_dict[obs_key]
            if metrics_sig in prior_metrics:
                # Subcase A: Exact Duplicate (dimensions and metrics are identical)
                warnings.append(
                    f"Row {row_idx}: Duplicate observation (exact duplicate) for '{term_text}' in campaign '{campaign_name}' "
                    f"on {obs_date} skipped to prevent spend inflation."
                )
                if quarantined_out is not None:
                    quarantined_out.append(
                        QuarantinedRow(
                            row_number=row_idx,
                            file_type="Search Terms",
                            search_term_or_campaign=term_text,
                            reason="Exact duplicate observation key and metrics (skipped to prevent spend inflation)",
                            raw_data=dict(row),
                        )
                    )
                continue
            elif not is_fully_segmented:
                # Subcase B: Distinct Segment with Missing Columns (e.g. multi-keyword or device segments without headers)
                # Ensure legitimate observations are not discarded!
                warnings.append(
                    f"Row {row_idx}: Additional distinct traffic segment for '{term_text}' in '{campaign_name}' "
                    f"on {obs_date} preserved (export lacks full segmentation columns: match type / keyword / IDs)."
                )
                prior_metrics.append(metrics_sig)
            else:
                # Subcase C: Ambiguous Duplicate Collision
                # Granular segment dimensions are fully specified and identical, yet metrics conflict!
                warnings.append(
                    f"Row {row_idx}: Ambiguous duplicate observation for '{term_text}' in '{campaign_name}' on {obs_date}; "
                    "conflicting metrics found for identical granular segment dimensions; row quarantined to protect metric integrity."
                )
                if quarantined_out is not None:
                    quarantined_out.append(
                        QuarantinedRow(
                            row_number=row_idx,
                            file_type="Search Terms",
                            search_term_or_campaign=term_text,
                            reason="Ambiguous duplicate: conflicting metrics for identical granular segment dimensions",
                            raw_data=dict(row),
                        )
                    )
                continue
        else:
            seen_row_dict[obs_key] = [metrics_sig]

        obs = SearchTermObservation(
            customer_id="csv_import",
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            ad_group_id=ad_group_id,
            ad_group_name=ad_group_name,
            search_term=term_text,
            date=obs_date,
            network=norm_network,
            match_source="ADVERTISER_PROVIDED_KEYWORD",
            search_term_match_type=match_type,
            targeting_status="NONE",
            triggering_keyword=kw_text,
            triggering_keyword_match_type=match_type if kw_text else None,
            impressions=impressions,
            clicks=clicks,
            cost_micros=cost_micros,
            conversions=conversions,
            conversions_value=conversions_value,
            all_conversions=conversions,
            all_conversions_value=conversions_value,
            currency_code=raw_currency,
        )
        observations.append(obs)

    if len(currencies_seen) > 1:
        raise CSVValidationError(
            f"Multiple currencies detected in search terms file: {', '.join(sorted(currencies_seen))}. "
            "A single currency is required."
        )

    return observations, warnings


def parse_campaign_spend_csv(
    file_content: str | bytes,
    default_currency: str = "USD",
    custom_mapping: Mapping[str, str] | None = None,
    quarantined_out: list[QuarantinedRow] | None = None,
) -> tuple[list[CampaignSpendObservation], list[str]]:
    """Parse Google Ads Campaign Performance report CSV into CampaignSpendObservation records.

    Deduplication Policy:
    Identical rows matching (date, campaign_id, campaign_name, network) are skipped to prevent
    inflating eligible campaign spend.
    """
    if isinstance(file_content, bytes):
        try:
            text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_content.decode("utf-16", errors="replace")
    else:
        text = file_content

    # Strip title/metadata rows if present
    text = _strip_metadata_header_lines(
        text, ["campaign", "campaign_name", "campaign name"]
    )

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CSVValidationError("Campaign spend CSV file is empty or missing headers")

    col_map = resolve_columns(reader.fieldnames, CAMPAIGN_SPEND_ALIASES, custom_mapping)

    if "cost" not in col_map:
        raise CSVValidationError(
            "Missing required column for 'Cost'. Available columns: "
            + ", ".join(reader.fieldnames)
        )

    observations: list[CampaignSpendObservation] = []
    warnings: list[str] = []
    currencies_seen: set[str] = set()
    seen_cs_dict: dict[tuple[date, str, str, str], list[int]] = {}

    has_campaign_id_col = "campaign_id" in col_map
    is_micros_col = "micros" in col_map["cost"].lower()

    for row_idx, row in enumerate(reader, start=2):
        campaign_name = (
            row.get(col_map.get("campaign_name", "")) or "Default Campaign"
        ).strip()

        # Skip summary totals
        camp_lower = campaign_name.lower()
        if (
            camp_lower.startswith("total:")
            or camp_lower == "total"
            or camp_lower in ("total: account", "total: campaigns", "account total")
        ):
            warnings.append(f"Row {row_idx}: Skipped Google Ads summary total row '{campaign_name}'")
            continue

        cost_val = row.get(col_map["cost"], "0")
        try:
            cost_micros = parse_money_to_micros(cost_val, is_already_micros=is_micros_col)
        except CSVValidationError:
            warnings.append(f"Row {row_idx}: Invalid cost '{cost_val}'; row quarantined.")
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Campaign Spend",
                        search_term_or_campaign=campaign_name,
                        reason=f"Invalid monetary cost value '{cost_val}'",
                        raw_data=dict(row),
                    )
                )
            continue

        raw_currency = (
            row.get(col_map.get("currency_code", ""))
            or default_currency
        ).strip().upper()
        if len(raw_currency) != 3 or not raw_currency.isalpha():
            raw_currency = default_currency.upper()
        currencies_seen.add(raw_currency)

        # 1. Date handling: Explicit row rejection on malformed or missing dates (No fallback)
        date_col = col_map.get("date")
        raw_date_val = (row.get(date_col) or "").strip() if date_col else ""
        if not raw_date_val:
            warnings.append(
                f"Row {row_idx}: Missing required date for campaign '{campaign_name}'; row quarantined."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Campaign Spend",
                        search_term_or_campaign=campaign_name,
                        reason="Missing required observation date",
                        raw_data=dict(row),
                    )
                )
            continue
        try:
            obs_date = parse_date(raw_date_val)
        except CSVValidationError:
            warnings.append(
                f"Row {row_idx}: Malformed date '{raw_date_val}' for campaign '{campaign_name}'; row quarantined."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Campaign Spend",
                        search_term_or_campaign=campaign_name,
                        reason=f"Malformed date '{raw_date_val}'",
                        raw_data=dict(row),
                    )
                )
            continue

        network_col = col_map.get("network")
        raw_network = (row.get(network_col) or "SEARCH").strip().upper()
        if "PARTNER" in raw_network:
            norm_network = "SEARCH_PARTNERS"
        elif "SEARCH" in raw_network:
            norm_network = "SEARCH"
        else:
            norm_network = raw_network

        if norm_network not in ALLOWED_NETWORKS:
            warnings.append(
                f"Row {row_idx}: Non-search network '{raw_network}' observed for campaign '{campaign_name}'; "
                "row quarantined from Search spend scope."
            )
            if quarantined_out is not None:
                quarantined_out.append(
                    QuarantinedRow(
                        row_number=row_idx,
                        file_type="Campaign Spend",
                        search_term_or_campaign=campaign_name,
                        reason=f"Non-search network '{raw_network}' outside Search/Search Partners scope",
                        raw_data=dict(row),
                    )
                )
            continue

        campaign_id = (
            row.get(col_map.get("campaign_id", ""))
            or f"c_{normalize_header(campaign_name)}"
        ).strip()

        # 3. Deduplication Policy & Fallback Strategy:
        # Prevent duplicate campaign spend from inflating denominator while preserving
        # legitimate unsegmented campaign breakdowns.
        cs_key = (obs_date, campaign_id.lower(), campaign_name.lower(), norm_network)
        if cs_key in seen_cs_dict:
            prior_costs = seen_cs_dict[cs_key]
            if cost_micros in prior_costs:
                # Exact duplicate campaign row
                warnings.append(
                    f"Row {row_idx}: Exact duplicate campaign spend row for '{campaign_name}' on {obs_date} "
                    "skipped to prevent eligible spend inflation."
                )
                if quarantined_out is not None:
                    quarantined_out.append(
                        QuarantinedRow(
                            row_number=row_idx,
                            file_type="Campaign Spend",
                            search_term_or_campaign=campaign_name,
                            reason="Exact duplicate campaign spend key and cost (skipped to prevent spend inflation)",
                            raw_data=dict(row),
                        )
                    )
                continue
            elif not has_campaign_id_col:
                # Legitimate unsegmented breakdown: e.g. campaign ID was missing from export
                warnings.append(
                    f"Row {row_idx}: Additional distinct campaign spend row for '{campaign_name}' on {obs_date} "
                    "preserved (export lacks campaign_id column)."
                )
                prior_costs.append(cost_micros)
            else:
                # Ambiguous duplicate: conflicting cost values for identical campaign ID
                warnings.append(
                    f"Row {row_idx}: Ambiguous duplicate campaign spend row for '{campaign_name}' on {obs_date}; "
                    "conflicting cost found for identical campaign ID; row quarantined."
                )
                if quarantined_out is not None:
                    quarantined_out.append(
                        QuarantinedRow(
                            row_number=row_idx,
                            file_type="Campaign Spend",
                            search_term_or_campaign=campaign_name,
                            reason="Ambiguous duplicate: conflicting cost values for identical campaign ID",
                            raw_data=dict(row),
                        )
                    )
                continue
        else:
            seen_cs_dict[cs_key] = [cost_micros]

        obs = CampaignSpendObservation(
            customer_id="csv_import",
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            date=obs_date,
            network=norm_network,
            cost_micros=cost_micros,
            currency_code=raw_currency,
        )
        observations.append(obs)

    if len(currencies_seen) > 1:
        raise CSVValidationError(
            f"Multiple currencies detected in campaign spend file: {', '.join(sorted(currencies_seen))}. "
            "A single currency is required."
        )

    return observations, warnings


@dataclass(slots=True)
class CompatibilityReport:
    is_compatible: bool
    currency_code: str
    search_term_count: int
    campaign_spend_count: int
    date_min: date | None
    date_max: date | None
    coverage_summary: CoverageSummary | None
    validation_messages: list[str] = field(default_factory=list)
    reconciled_search_terms: list[SearchTermObservation] = field(default_factory=list)
    reconciled_campaign_spend: list[CampaignSpendObservation] = field(default_factory=list)
    has_date_reconciliation: bool = False
    quarantined_records: list[QuarantinedRow] = field(default_factory=list)


def validate_compatibility(
    search_terms: Sequence[SearchTermObservation],
    campaign_spend: Sequence[CampaignSpendObservation],
    quarantined_out: list[QuarantinedRow] | None = None,
) -> CompatibilityReport:
    """Validate cross-dataset currency, date compatibility, and calculate CoverageSummary.

    Date Reconciliation Policy:
    If reports span differing date periods, spend coverage is computed strictly
    over the verified common period [max(st_min, cs_min), min(st_max, cs_max)]
    to prevent denominator or numerator skew. If periods are disjoint, analysis is rejected.

    Reconciliation Warning Policy:
    If visible search-term spend exceeds eligible campaign spend, an explicit
    discrepancy warning is raised rather than hiding the defect under a 100% cap.
    """
    messages: list[str] = []
    quarantined_records = list(quarantined_out or [])

    if not search_terms:
        messages.append("No search term observations provided.")
    if not campaign_spend:
        messages.append("No campaign spend observations provided.")

    if not search_terms or not campaign_spend:
        return CompatibilityReport(
            is_compatible=False,
            currency_code="",
            search_term_count=len(search_terms),
            campaign_spend_count=len(campaign_spend),
            date_min=None,
            date_max=None,
            coverage_summary=None,
            validation_messages=messages,
            reconciled_search_terms=[],
            reconciled_campaign_spend=[],
            has_date_reconciliation=False,
            quarantined_records=quarantined_records,
        )

    # 1. Currency validation
    st_currencies = {st.currency_code for st in search_terms}
    cs_currencies = {cs.currency_code for cs in campaign_spend}

    if len(st_currencies) != 1 or len(cs_currencies) != 1:
        messages.append(
            f"Mixed currencies found (Search terms: {st_currencies}, Campaign: {cs_currencies})"
        )
        return CompatibilityReport(
            is_compatible=False,
            currency_code="",
            search_term_count=len(search_terms),
            campaign_spend_count=len(campaign_spend),
            date_min=None,
            date_max=None,
            coverage_summary=None,
            validation_messages=messages,
            reconciled_search_terms=[],
            reconciled_campaign_spend=[],
            has_date_reconciliation=False,
            quarantined_records=quarantined_records,
        )

    st_curr = next(iter(st_currencies))
    cs_curr = next(iter(cs_currencies))

    if st_curr != cs_curr:
        messages.append(
            f"Currency mismatch: Search terms report uses {st_curr}, but Campaign report uses {cs_curr}."
        )
        return CompatibilityReport(
            is_compatible=False,
            currency_code=st_curr,
            search_term_count=len(search_terms),
            campaign_spend_count=len(campaign_spend),
            date_min=None,
            date_max=None,
            coverage_summary=None,
            validation_messages=messages,
            reconciled_search_terms=[],
            reconciled_campaign_spend=[],
            has_date_reconciliation=False,
            quarantined_records=quarantined_records,
        )

    # 2. Date compatibility & common period verification (Correction 2)
    st_dates = [st.date for st in search_terms]
    cs_dates = [cs.date for cs in campaign_spend]
    st_min, st_max = min(st_dates), max(st_dates)
    cs_min, cs_max = min(cs_dates), max(cs_dates)

    common_min = max(st_min, cs_min)
    common_max = min(st_max, cs_max)

    if common_min > common_max:
        messages.append(
            f"Date range mismatch: Search terms report ({st_min} to {st_max}) does not overlap "
            f"with Campaign report ({cs_min} to {cs_max}). Cannot reliably compare spend across disjoint periods."
        )
        return CompatibilityReport(
            is_compatible=False,
            currency_code=st_curr,
            search_term_count=len(search_terms),
            campaign_spend_count=len(campaign_spend),
            date_min=min(st_min, cs_min),
            date_max=max(st_max, cs_max),
            coverage_summary=None,
            validation_messages=messages,
            reconciled_search_terms=[],
            reconciled_campaign_spend=[],
            has_date_reconciliation=False,
            quarantined_records=quarantined_records,
        )

    has_date_diff = (st_min != cs_min) or (st_max != cs_max)
    if has_date_diff:
        reconciled_st = [st for st in search_terms if common_min <= st.date <= common_max]
        reconciled_cs = [cs for cs in campaign_spend if common_min <= cs.date <= common_max]
        st_excluded = [st for st in search_terms if not (common_min <= st.date <= common_max)]
        cs_excluded = [cs for cs in campaign_spend if not (common_min <= cs.date <= common_max)]

        for st in st_excluded:
            q_row = QuarantinedRow(
                row_number=0,
                file_type="Search Terms",
                search_term_or_campaign=st.search_term,
                reason=f"Date {st.date} outside verified common period [{common_min} to {common_max}]",
                raw_data={"date": str(st.date), "cost": st.cost.format(), "campaign": st.campaign_name},
            )
            quarantined_records.append(q_row)
            if quarantined_out is not None:
                quarantined_out.append(q_row)

        for cs in cs_excluded:
            q_row = QuarantinedRow(
                row_number=0,
                file_type="Campaign Spend",
                search_term_or_campaign=cs.campaign_name,
                reason=f"Date {cs.date} outside verified common period [{common_min} to {common_max}]",
                raw_data={"date": str(cs.date), "cost_micros": cs.cost_micros, "campaign": cs.campaign_name},
            )
            quarantined_records.append(q_row)
            if quarantined_out is not None:
                quarantined_out.append(q_row)

        messages.append(
            f"Date range reconciliation: Reports have differing ranges (Search terms: {st_min} to {st_max}, "
            f"Campaign: {cs_min} to {cs_max}). Spend coverage calculated strictly over the verified common "
            f"period: {common_min.isoformat()} to {common_max.isoformat()} "
            f"({len(st_excluded)} search-term rows and {len(cs_excluded)} campaign rows outside this period excluded from coverage comparison)."
        )
    else:
        reconciled_st = list(search_terms)
        reconciled_cs = list(campaign_spend)

    # 3. Campaign scope overlap advisory
    st_campaigns = {st.campaign_name.strip().lower() for st in reconciled_st}
    cs_campaigns = {cs.campaign_name.strip().lower() for cs in reconciled_cs}
    unmatched_campaigns = st_campaigns - cs_campaigns
    if unmatched_campaigns:
        messages.append(
            f"Scope notice: {len(unmatched_campaigns)} campaign(s) in the search-term report were not found "
            "in the campaign performance report."
        )

    cov = summarize_coverage(reconciled_st, reconciled_cs)

    # 5. Reconciliation warning when visible search spend exceeds campaign spend (Correction 5)
    if cov.has_reconciliation_discrepancy:
        excess_money = Money(cov.reconciliation_excess_micros, cov.currency_code)
        raw_pct = f"{cov.raw_ratio * 100:.1f}%" if cov.raw_ratio else "N/A"
        messages.append(
            f"Reconciliation warning: Visible search-term spend ({Money(cov.visible_search_term_cost_micros, cov.currency_code).format()}) "
            f"exceeds eligible campaign spend ({Money(cov.eligible_search_campaign_cost_micros, cov.currency_code).format()}) "
            f"by {excess_money.format()} (raw ratio: {raw_pct}). The 100% capped display does not hide this discrepancy."
        )

    return CompatibilityReport(
        is_compatible=True,
        currency_code=st_curr,
        search_term_count=len(reconciled_st),
        campaign_spend_count=len(reconciled_cs),
        date_min=common_min,
        date_max=common_max,
        coverage_summary=cov,
        validation_messages=messages,
        reconciled_search_terms=reconciled_st,
        reconciled_campaign_spend=reconciled_cs,
        has_date_reconciliation=has_date_diff,
        quarantined_records=quarantined_records,
    )
