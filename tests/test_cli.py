from argparse import Namespace
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from result_scraper.cli import run
from result_scraper.scraper import DrawResult
from result_scraper.workbook import load_existing_results


class ConcurrentCollectionTests(unittest.TestCase):
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

