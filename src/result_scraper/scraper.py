"""Fetch and parse Nam Dinh grand-prize results from the official source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import html as html_module
from http.client import HTTPException
import os
import re
import socket
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from lxml import html


PRIMARY_URL = (
    "https://www.thinhnam.net.in/ket-qua-xo-so-mien-nam.php?ngay={date}"
)
FALLBACK_URL = "https://www.thinhnam.net.in/xo-so-mien-nam.php?ngay={date}"
SOURCE_HOST = "www.thinhnam.net.in"

_FIVE_DIGITS = re.compile(r"(?<!\d)(\d{5})(?!\d)")
_PROVINCE_CODE = re.compile(r"\bXS[A-Z0-9]{3,8}\b", re.IGNORECASE)


class ScrapeError(RuntimeError):
    """The page could not be fetched or did not contain a valid result."""


class ResultNotPublished(ScrapeError):
    """The requested date is present, but its result is not published yet."""


@dataclass(frozen=True, slots=True)
class DrawResult:
    draw_date: date
    grand_prize: str
    source_url: str

    def __post_init__(self) -> None:
        validate_prize(self.grand_prize)

    @property
    def digits(self) -> tuple[str, str, str, str, str]:
        first, second, third, fourth, fifth = self.grand_prize
        return first, second, third, fourth, fifth


def validate_prize(value: str) -> str:
    if not re.fullmatch(r"\d{5}", value):
        raise ValueError(f"grand prize must contain exactly five digits, got {value!r}")
    return value


def source_url(draw_date: date, template: str = PRIMARY_URL) -> str:
    return template.format(date=draw_date.isoformat())


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    folded = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    ).casefold()
    # Vietnamese D-with-stroke does not decompose under NFKD.
    return folded.replace("đ", "d")


def _clean_text(node: object) -> str:
    if hasattr(node, "itertext"):
        value = " ".join(str(part) for part in node.itertext())
    else:
        value = str(node)
    return " ".join(html_module.unescape(value).split())


def _date_tokens(draw_date: date) -> tuple[str, ...]:
    return (
        draw_date.strftime("%d/%m/%Y"),
        f"{draw_date.day}/{draw_date.month}/{draw_date.year}",
        draw_date.isoformat(),
    )


def _has_requested_date(text: str, draw_date: date) -> bool:
    return any(token in text for token in _date_tokens(draw_date))


def _direct_cells(row: object) -> list[object]:
    cells = row.xpath("./th | ./td")
    return cells if cells else row.xpath(".//th | .//td")


def _is_special_label(text: str) -> bool:
    folded = _fold(text)
    return "giai dac biet" in folded or re.search(r"\bgiai\s+d[bb]\b", folded) is not None


def _find_province_column(rows: list[object]) -> int | None:
    fallback_index: int | None = None
    for row in rows:
        for index, cell in enumerate(_direct_cells(row)):
            folded = _fold(_clean_text(cell))
            if "nam dinh" in folded:
                return index
            if "xsndh" in folded and fallback_index is None:
                fallback_index = index
    return fallback_index


def _extract_from_table(table: object) -> str | None:
    rows = table.xpath(".//tr")
    province_index = _find_province_column(rows)

    for row in rows:
        cells = _direct_cells(row)
        if not cells:
            continue

        label_index = next(
            (
                index
                for index, cell in enumerate(cells)
                if _is_special_label(_clean_text(cell))
            ),
            None,
        )
        if label_index is None:
            continue

        if province_index is not None and province_index < len(cells):
            matches = _FIVE_DIGITS.findall(_clean_text(cells[province_index]))
            if len(matches) == 1:
                return matches[0]

        for cell in cells[label_index + 1 :]:
            matches = _FIVE_DIGITS.findall(_clean_text(cell))
            if len(matches) == 1:
                return matches[0]
    return None


def _extract_from_text(root_text: str, draw_date: date) -> str | None:
    markers = list(re.finditer(r"\bXSNDH\b", root_text, re.IGNORECASE))
    if not markers:
        return None

    date_tokens = _date_tokens(draw_date)

    def marker_score(marker: re.Match[str]) -> tuple[int, int]:
        prefix = root_text[max(0, marker.start() - 2500) : marker.start()]
        positions = [prefix.rfind(token) for token in date_tokens]
        closest = max(positions)
        return (1 if closest >= 0 else 0, closest)

    for marker in sorted(markers, key=marker_score, reverse=True):
        remainder = root_text[marker.end() : marker.end() + 3000]
        next_code = _PROVINCE_CODE.search(remainder)
        segment = remainder[: next_code.start()] if next_code else remainder
        candidates = _FIVE_DIGITS.findall(segment)
        if candidates:
            return candidates[-1]
    return None


def parse_special_prize(page: bytes | str, draw_date: date) -> str:
    """Return the five-digit Nam Dinh grand prize for ``draw_date``.

    The primary strategy uses the visual table relationship confirmed on the
    official page: the Nam Dinh column intersecting the ``Giai Dac Biet`` row.
    A text-structure fallback handles harmless markup changes while remaining
    scoped to the Nam Dinh ``XSNDH`` province block.
    """

    try:
        root = html.fromstring(page)
    except (ValueError, TypeError) as exc:
        raise ScrapeError(f"official page was not valid HTML: {exc}") from exc

    root_text = _clean_text(root)
    if not _has_requested_date(root_text, draw_date):
        raise ResultNotPublished(
            f"official page does not contain requested date {draw_date.isoformat()}"
        )

    candidates: list[tuple[int, int, object]] = []
    for position, table in enumerate(root.xpath("//table")):
        table_text = _clean_text(table)
        folded = _fold(table_text)
        if "nam dinh" not in folded and "xsndh" not in folded:
            continue
        if "giai dac biet" not in folded and "giai db" not in folded:
            continue
        score = 0
        score += 8 if _has_requested_date(table_text, draw_date) else 0
        score += 4 if "nam dinh" in folded else 0
        score += 2 if "xsndh" in folded else 0
        candidates.append((score, -position, table))

    for _, _, table in sorted(candidates, reverse=True, key=lambda item: item[:2]):
        prize = _extract_from_table(table)
        if prize is not None:
            return validate_prize(prize)

    prize = _extract_from_text(root_text, draw_date)
    if prize is not None:
        return validate_prize(prize)

    raise ResultNotPublished(
        f"Nam Dinh grand prize is not available for {draw_date.isoformat()}"
    )


def parse_reader_special_prize(page: bytes | str, draw_date: date) -> str:
    """Parse a Thinhnam page converted to Markdown by a reader relay."""

    if isinstance(page, bytes):
        text = page.decode("utf-8", errors="replace")
    else:
        text = page

    display_date = draw_date.strftime("%d/%m/%Y")
    marker = re.search(
        rf"\[{re.escape(display_date)}\s*-\s*13h15[^\]]*\]",
        text,
        re.IGNORECASE,
    )
    if marker is None:
        raise ResultNotPublished(
            f"reader page does not contain requested date {draw_date.isoformat()}"
        )

    segment = text[marker.start() :]
    next_result = segment.find("[KẾT QUẢ XỔ SỐ Miền Nam]", 1)
    if next_result >= 0:
        segment = segment[:next_result]

    province = re.search(
        r"Nam Định.*?\bXSNDH\b(?P<body>.*?)(?:Đà Nẵng|\bXSDNG\b)",
        segment,
        re.IGNORECASE | re.DOTALL,
    )
    if province is None:
        raise ResultNotPublished(
            f"Nam Dinh result is not available for {draw_date.isoformat()}"
        )

    candidates = _FIVE_DIGITS.findall(province.group("body"))
    if not candidates:
        raise ResultNotPublished(
            f"Nam Dinh grand prize is not available for {draw_date.isoformat()}"
        )
    return validate_prize(candidates[-1])


def _reader_url(url: str, reader_base: str) -> str:
    parsed = urlsplit(url)
    return f"{reader_base.rstrip('/')}/http://{parsed.netloc}{parsed.path}?{parsed.query}"


def scrape_date(
    draw_date: date,
    *,
    timeout_seconds: float = 45.0,
    max_attempts: int = 4,
) -> DrawResult:
    """Fetch one date from Thinhnam, retrying transient failures."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    templates = (PRIMARY_URL, FALLBACK_URL)
    errors: list[str] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
            "result-scrapper/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi,en-US;q=0.8,en;q=0.6",
        "Cache-Control": "no-cache",
    }
    proxy_url = os.environ.get("THINHNAM_PROXY_URL", "").strip()
    reader_base = os.environ.get("THINHNAM_READER_BASE", "").strip()
    opener = (
        build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        if proxy_url
        else build_opener()
    )

    for attempt in range(1, max_attempts + 1):
        for template in templates:
            url = source_url(draw_date, template)
            request_url = _reader_url(url, reader_base) if reader_base else url
            request_headers = (
                {"User-Agent": "curl/8.10.1", "Accept": "text/plain"}
                if reader_base
                else headers
            )
            request = Request(request_url, headers=request_headers, method="GET")
            try:
                with opener.open(request, timeout=timeout_seconds) as response:
                    body = response.read(8_000_001)
                    if len(body) > 8_000_000:
                        raise ScrapeError("official page exceeded the 8 MB safety limit")
                    prize = (
                        parse_reader_special_prize(body, draw_date)
                        if reader_base
                        else parse_special_prize(body, draw_date)
                    )
                    return DrawResult(draw_date, prize, url)
            except (
                HTTPError,
                URLError,
                TimeoutError,
                socket.timeout,
                HTTPException,
                ScrapeError,
            ) as exc:
                errors.append(f"{request_url}: {type(exc).__name__}: {exc}")

        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 20))

    detail = "; ".join(errors[-4:])
    raise ScrapeError(
        f"failed to collect {draw_date.isoformat()} after {max_attempts} attempts: {detail}"
    )

