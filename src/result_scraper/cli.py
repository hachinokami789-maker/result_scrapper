"""Command-line entry point for backfill and daily collection."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from .scraper import DrawResult, ScrapeError, scrape_date
from .workbook import DEFAULT_OUTPUT, ensure_workbook, load_existing_results, upsert_results


START_DATE = date(2020, 4, 2)
TIMEZONE = ZoneInfo("Asia/Phnom_Penh")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def _today_ict() -> date:
    from datetime import datetime

    return datetime.now(TIMEZONE).date()


def _date_range(start_date: date, end_date: date) -> list[date]:
    if end_date < start_date:
        raise ValueError("end date cannot be before start date")
    days = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(days + 1)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Nam Dinh five-digit grand-prize results from the official "
            "Thinhnam website and store them in Excel."
        )
    )
    parser.add_argument("--start-date", type=_parse_date, default=START_DATE)
    parser.add_argument("--end-date", type=_parse_date, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Fetch dates even if they are already present in the workbook.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Exit successfully even when one or more dates could not be collected.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    end_date = args.end_date or _today_ict()
    if args.delay < 0:
        raise ValueError("delay cannot be negative")
    if args.checkpoint_every < 1:
        raise ValueError("checkpoint-every must be at least 1")

    ensure_workbook(args.output)
    existing = load_existing_results(args.output)
    requested_dates = _date_range(args.start_date, end_date)
    pending = (
        requested_dates
        if args.refresh_existing
        else [draw_date for draw_date in requested_dates if draw_date not in existing]
    )

    print(
        f"Requested {len(requested_dates)} dates ({args.start_date} through {end_date}); "
        f"{len(requested_dates) - len(pending)} already stored; {len(pending)} pending."
    )

    batch: list[DrawResult] = []
    failures: list[tuple[date, str]] = []
    for index, draw_date in enumerate(pending, start=1):
        try:
            result = scrape_date(
                draw_date,
                max_attempts=args.max_attempts,
            )
        except ScrapeError as exc:
            failures.append((draw_date, str(exc)))
            print(f"ERROR {draw_date}: {exc}", file=sys.stderr)
        else:
            batch.append(result)
            print(
                f"OK {draw_date}: {result.grand_prize} "
                f"-> {result.variation_c}, {result.variation_d}"
            )

        if batch and (len(batch) >= args.checkpoint_every or index == len(pending)):
            total = upsert_results(args.output, batch)
            print(f"Checkpoint saved: {total} total rows in {args.output}")
            batch.clear()

        if index < len(pending) and args.delay:
            time.sleep(args.delay)

    if batch:
        total = upsert_results(args.output, batch)
        print(f"Final checkpoint saved: {total} total rows in {args.output}")

    total_stored = len(load_existing_results(args.output))
    print(
        f"Finished with {total_stored} stored rows and {len(failures)} failed dates."
    )
    if failures and not args.allow_missing:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
