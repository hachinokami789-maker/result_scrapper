from argparse import Namespace
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from result_scraper.cli import HISTORICAL_DRAW_PARITY, _is_scheduled_draw_date, run
from result_scraper.scraper import DrawResult
from result_scraper.workbook import load_existing_results


class ConcurrentCollectionTests(unittest.TestCase):
    def test_historical_schedule_and_april_first_skip(self) -> None:
        expected_parity = {
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
        self.assertEqual(HISTORICAL_DRAW_PARITY, expected_parity)
        for (year, month), parity in expected_parity.items():
            matching_day = 2 if parity == 0 else 3
            opposite_day = 3 if parity == 0 else 2
            self.assertTrue(_is_scheduled_draw_date(date(year, month, matching_day)))
            self.assertFalse(_is_scheduled_draw_date(date(year, month, opposite_day)))
        self.assertTrue(_is_scheduled_draw_date(date(2020, 3, 31)))
        self.assertFalse(_is_scheduled_draw_date(date(2020, 4, 1)))
        self.assertTrue(_is_scheduled_draw_date(date(2020, 4, 2)))

    def test_multiple_workers_store_every_date(self) -> None:
        start = date(2026, 8, 9)
        end = date(2026, 8, 11)

        def fake_scrape(draw_date: date, **_: object) -> DrawResult:
            prize = f"{draw_date.day:05d}"
            return DrawResult(draw_date, prize, f"https://official.test/{draw_date}")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.xlsx"
            args = Namespace(
                start_date=start,
                end_date=end,
                output=output,
                delay=0,
                checkpoint_every=2,
                max_attempts=1,
                timeout=1.0,
                workers=3,
                refresh_existing=False,
                allow_missing=False,
            )

            with patch("result_scraper.cli.scrape_date", new=fake_scrape):
                exit_code = run(args)

            results = load_existing_results(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(sorted(results), [start, date(2026, 8, 10), end])


if __name__ == "__main__":
    unittest.main()

