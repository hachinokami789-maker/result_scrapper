"""Command-line entry point for backfill and daily collection."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from .scraper import DrawResult, ScrapeError, scrape_date
from .workbook import DEFAULT_OUTPUT, ensure_workbook, load_existing_results, upsert_results


START_DATE = date(2019, 1, 1)
TIMEZONE = ZoneInfo("Asia/Phnom_Penh")

HISTORICAL_DRAW_PARITY = {
    (2019, 1): 0,
    (2019, 2): 1,
    (2019, 3): 1,
    (2019, 4): 0,
    (2019, 5): 0,
    (2019, 6): 1,
    (2019, 7): 1,
    (2019, 8): 0,
    (2019, 9): 1,
    (2019, 10): 1,
    (2019, 11): 0,
    (2019, 12): 0,
    (2020, 1): 1,
    (2020, 2): 0,
    (2020, 3): 1,
}
SKIPPED_DRAW_DATES = {date(2020, 4, 1)}


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


def _is_scheduled_draw_date(draw_date: date) -> bool:
    if draw_date in SKIPPED_DRAW_DATES:
        return False
    parity = HISTORICAL_DRAW_PARITY.get((draw_date.year, draw_date.month))
    return parity is None or draw_date.day % 2 == parity


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
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent date fetches (the workflow uses a conservative 3).",
    )
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
    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    if args.workers < 1:
        raise ValueError("workers must be at least 1")
    if args.checkpoint_every < 1:
        raise ValueError("checkpoint-every must be at least 1")

    ensure_workbook(args.output)
    existing = load_existing_results(args.output)
    requested_dates = _date_range(args.start_date, end_date)
    scheduled_dates = [
        draw_date for draw_date in requested_dates if _is_scheduled_draw_date(draw_date)
    ]
    pending = (
        scheduled_dates
        if args.refresh_existing
        else [draw_date for draw_date in scheduled_dates if draw_date not in existing]
    )

    print(
        f"Requested {len(requested_dates)} calendar dates ({args.start_date} through "
        f"{end_date}); {len(scheduled_dates)} scheduled draw dates; "
        f"{len(scheduled_dates) - len(pending)} already stored; {len(pending)} pending."
    )

    def fetch_one(draw_date: date) -> tuple[date, DrawResult | None, str | None]:
        try:
            result = scrape_date(
                draw_date,
                timeout_seconds=args.timeout,
                max_attempts=args.max_attempts,
            )
        except ScrapeError as exc:
            return draw_date, None, str(exc)
        else:
            return draw_date, result, None
        finally:
            if args.delay:
                time.sleep(args.delay)

    def outcomes() -> Iterator[tuple[date, DrawResult | None, str | None]]:
        if args.workers == 1:
            for draw_date in pending:
                yield fetch_one(draw_date)
            return

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(fetch_one, draw_date) for draw_date in pending]
            for future in as_completed(futures):
                yield future.result()

    batch: list[DrawResult] = []
    failures: list[tuple[date, str]] = []
    for index, (draw_date, result, error) in enumerate(outcomes(), start=1):
        if error is not None:
            failures.append((draw_date, error))
            print(f"ERROR {draw_date}: {error}", file=sys.stderr)
        else:
            assert result is not None
            batch.append(result)
            print(
                f"OK {draw_date}: {result.grand_prize} "
                f"-> {', '.join(result.digits)}"
            )

        if batch and (len(batch) >= args.checkpoint_every or index == len(pending)):
            total = upsert_results(args.output, batch)
            print(f"Checkpoint saved: {total} total rows in {args.output}")
            batch.clear()

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

