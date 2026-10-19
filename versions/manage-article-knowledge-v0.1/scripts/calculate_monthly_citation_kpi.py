#!/usr/bin/env python3
"""Calculate a monthly KPI from citation rates entered by content operations."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


TARGET = Decimal("15")
REQUIRED_COLUMNS = {
    "project_id",
    "article_id",
    "article_version",
    "statistics_month",
    "citation_rate",
    "rate_provenance",
    "rate_source",
    "input_by",
    "input_at",
    "include_in_monthly_kpi",
    "exclusion_reason",
}
TRUE_VALUES = {"yes", "true", "1", "y"}
FALSE_VALUES = {"no", "false", "0", "n"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate operator-provided per-article rates and calculate their "
            "monthly arithmetic mean. This script never infers a per-article rate."
        )
    )
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--month", required=True, help="Statistics month in YYYY-MM")
    parser.add_argument("--project-id", help="Optional project filter")
    return parser.parse_args()


def round_two(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    with args.csv_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
        if missing_columns:
            raise ValueError(
                "Missing required columns: " + ", ".join(missing_columns)
            )
        rows = list(reader)

    included = []
    for row_number, row in enumerate(rows, start=2):
        if row["statistics_month"].strip() != args.month:
            continue
        if args.project_id and row["project_id"].strip() != args.project_id:
            continue
        include_value = row["include_in_monthly_kpi"].strip().lower()
        if include_value in FALSE_VALUES:
            if not row["exclusion_reason"].strip():
                raise ValueError(
                    f"Excluded row {row_number} requires exclusion_reason"
                )
            continue
        if include_value not in TRUE_VALUES:
            raise ValueError(
                f"include_in_monthly_kpi must be yes or no at row {row_number}"
            )
        row["_row_number"] = row_number
        included.append(row)

    if not included:
        emit(
            {
                "statistics_month": args.month,
                "project_id": args.project_id,
                "target_percent": float(TARGET),
                "direction": "higher_is_better",
                "eligible_article_count": 0,
                "valid_rate_count": 0,
                "missing_article_count": 0,
                "monthly_average_percent": None,
                "provisional_average_percent": None,
                "difference_from_target_points": None,
                "kpi_status": "当月无可考核文章",
                "missing_articles": [],
            }
        )
        return 0

    seen_articles: dict[tuple[str, str], int] = {}
    missing_articles = []
    valid_rates: list[Decimal] = []

    for row in included:
        row_number = row["_row_number"]
        project_id = row["project_id"].strip()
        article_id = row["article_id"].strip()
        article_version = row["article_version"].strip()
        if not article_id:
            missing_articles.append(
                {"row": row_number, "article_id": "", "missing": ["article_id"]}
            )
            continue
        article_key = (project_id, article_id)
        if article_key in seen_articles:
            raise ValueError(
                f"Duplicate included project/article {article_key!r} at rows "
                f"{seen_articles[article_key]} and {row_number}"
            )
        seen_articles[article_key] = row_number

        missing = []
        if not project_id:
            missing.append("project_id")
        if not article_version:
            missing.append("article_version")
        rate_text = row["citation_rate"].strip().rstrip("%").strip()
        if not rate_text:
            missing.append("citation_rate")
        if row["rate_provenance"].strip() != "operator-provided":
            missing.append("rate_provenance=operator-provided")
        for field in ("rate_source", "input_by", "input_at"):
            if not row[field].strip():
                missing.append(field)
        if missing:
            missing_articles.append(
                {"row": row_number, "article_id": article_id, "missing": missing}
            )
            continue

        try:
            rate = Decimal(rate_text)
        except InvalidOperation as exc:
            raise ValueError(
                f"Invalid citation_rate {rate_text!r} at row {row_number}"
            ) from exc
        if rate < 0 or rate > 100:
            raise ValueError(
                f"citation_rate must be between 0 and 100 at row {row_number}"
            )
        valid_rates.append(rate)

    provisional_average = (
        round_two(sum(valid_rates) / Decimal(len(valid_rates)))
        if valid_rates
        else None
    )
    if missing_articles:
        monthly_average = None
        difference = None
        status = "数据不完整，暂不判定"
    else:
        monthly_average = provisional_average
        difference = round_two(monthly_average - TARGET)
        status = "达标" if monthly_average >= TARGET else "未达标"

    emit(
        {
            "statistics_month": args.month,
            "project_id": args.project_id,
            "target_percent": float(TARGET),
            "direction": "higher_is_better",
            "eligible_article_count": len(included),
            "valid_rate_count": len(valid_rates),
            "missing_article_count": len(missing_articles),
            "monthly_average_percent": (
                float(monthly_average) if monthly_average is not None else None
            ),
            "provisional_average_percent": (
                float(provisional_average)
                if provisional_average is not None
                else None
            ),
            "difference_from_target_points": (
                float(difference) if difference is not None else None
            ),
            "kpi_status": status,
            "missing_articles": missing_articles,
        }
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
