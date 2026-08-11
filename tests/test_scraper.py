from datetime import date
import unittest

from result_scraper.scraper import (
    DrawResult,
    ResultNotPublished,
    parse_special_prize,
)


DRAW_DATE = date(2026, 8, 11)


TABLE_HTML = """
<!doctype html>
<html><body>
  <table id="southern-results">
    <tr><th>Chủ nhật</th><th>Nam Định</th><th>Đà Nẵng</th><th>Quảng Ngãi</th></tr>
    <tr><td>11/08/2026</td><td>XSNDH</td><td>XSDNG</td><td>XSDNG</td></tr>
    <tr><td>Giải tám</td><td>04</td><td>46</td><td>73</td></tr>
    <tr><td>Giải nhất</td><td>11362</td><td>70234</td><td>66876</td></tr>
    <tr><td><a>Giải Đặc Biệt</a></td><td><strong>33775</strong></td><td>91490</td><td>98803</td></tr>
  </table>
</body></html>
"""


TEXT_FALLBACK_HTML = """
<html><body>
  <section>KẾT QUẢ XỔ SỐ Miền Nam - 11/08/2026 - 13h15’</section>
  <div>Nam Định XSNDH 04 482 3686 0414 0087 95545 49097 96696 40040
  23208 44986 97414 91893 11362 33775</div>
  <div>Đà Nẵng XSDNG 46 425 0234 0329 2720 63640 29702 25036 78913
  87185 44341 88254 44374 70234 91490</div>
</body></html>
"""


class ParseTests(unittest.TestCase):
    def test_extracts_first_province_special_prize(self) -> None:
        self.assertEqual(parse_special_prize(TABLE_HTML, DRAW_DATE), "33775")

    def test_text_structure_fallback_uses_last_five_digit_value(self) -> None:
        self.assertEqual(parse_special_prize(TEXT_FALLBACK_HTML, DRAW_DATE), "33775")

    def test_requires_requested_date(self) -> None:
        with self.assertRaises(ResultNotPublished):
            parse_special_prize(TABLE_HTML, date(2026, 8, 10))

    def test_variations_match_user_rules(self) -> None:
        result = DrawResult(DRAW_DATE, "12345", "https://www.thinhnam.net.in/")
        self.assertEqual(result.variation_c, "45123")
        self.assertEqual(result.variation_d, "15234")

    def test_variations_preserve_leading_zero(self) -> None:
        result = DrawResult(DRAW_DATE, "01234", "https://www.thinhnam.net.in/")
        self.assertEqual(result.variation_c, "34012")
        self.assertEqual(result.variation_d, "04123")


if __name__ == "__main__":
    unittest.main()
