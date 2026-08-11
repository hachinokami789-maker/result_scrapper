"""Nam Dinh lottery result scraper."""

from .scraper import DrawResult, ResultNotPublished, ScrapeError, parse_special_prize

__all__ = [
    "DrawResult",
    "ResultNotPublished",
    "ScrapeError",
    "parse_special_prize",
]
