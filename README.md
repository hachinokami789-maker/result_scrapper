# Nam Định Grand Prize Scraper

This project collects the five-digit Nam Định `Giải Đặc Biệt` (grand prize)
from the official Thinhnam southern-region result page and stores a
date-sorted history in an Excel workbook.

Official source only:

`https://www.thinhnam.net.in/ket-qua-xo-so-mien-nam.php?ngay=YYYY-MM-DD`

## Workbook

The canonical workbook is:

`outputs/result_scraping/nam_dinh_results.xlsx`

It contains exactly four columns:

| Column | Content | Example for `12345` |
| --- | --- | --- |
| A | Date | `2026-08-11` |
| B | Nam Định grand prize | `12345` |
| C | Last two digits moved to the front | `45123` |
| D | Last digit moved behind the first | `15234` |

Columns B–D use an explicit five-digit number format so leading zeroes are
visible. Columns C and D are auditable Excel formulas based on Column B, so all
three results remain five digits. Each date is unique: rerunning the scraper
replaces that date instead of creating a duplicate.

## Automation

The GitHub Actions workflow runs daily at **13:45 Indochina Time**
(**06:45 UTC**) and can also be started manually. Every run checks the full
requested range beginning on **2020-04-02**, skips dates already in the
workbook, and fetches only missing dates. This makes the first run a resumable
historical backfill and later runs inexpensive daily updates.

The scraper checkpoints the workbook every 25 successful dates. If the site is
temporarily unavailable or a result has not been published, the workflow still
commits completed checkpoints, reports a failure, and retries only the missing
dates on the next run.

### Restricted-network access

The workflow automatically starts a Tor route when Thinhnam is not directly
reachable. This is self-contained on the GitHub-hosted runner: no browser VPN,
account, or credentials are required, and the scraper still requests only the
official Thinhnam URLs listed above.

If the site rejects Tor traffic, an optional private HTTP/HTTPS proxy can be
used instead. Add a repository Actions secret named `THINHNAM_PROXY_URL` whose
value is the complete proxy URL, for example
`http://user:password@proxy.example:8080`. Never commit that URL or its
credentials to the repository. When this secret exists, the workflow uses it
instead of Tor.

The workflow checks a known result page before starting the long backfill, so
network failures stop quickly without discarding an existing workbook.

## Run locally

Python 3.11 or newer is required.

```bash
python -m pip install -e .
python -m result_scraper \
  --start-date 2020-04-02 \
  --output outputs/result_scraping/nam_dinh_results.xlsx
```

To fetch one specific date:

```bash
python -m result_scraper \
  --start-date 2026-08-11 \
  --end-date 2026-08-11 \
  --refresh-existing
```

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```

The parser validates the requested date, selects the Nam Định column, locates
the `Giải Đặc Biệt` row, and rejects any value that is not exactly five digits.
It uses a short delay plus bounded retries to avoid placing unnecessary load on
the official site.

