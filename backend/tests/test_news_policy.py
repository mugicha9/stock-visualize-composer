from __future__ import annotations

import unittest

from backend.app.services.news_policy import canonical_news_url, decide_company_news


class NewsPolicyTest(unittest.TestCase):
    def test_ignores_low_value_recurring_columns(self) -> None:
        decision = decide_company_news("本日の【低PBR】10選", "株探")
        self.assertEqual(decision.action, "ignore")

    def test_summarizes_geopolitical_and_policy_news(self) -> None:
        decision = decide_company_news("中東情勢悪化で原油高、化学メーカーにコスト圧力", "ロイター")
        self.assertEqual(decision.action, "summarize")

    def test_keeps_unclassified_kabutan_as_title_only(self) -> None:
        decision = decide_company_news("ABC社が年初来高値を更新", "株探ニュース")
        self.assertEqual(decision.action, "title_only")

    def test_canonical_url_drops_tracking_parts(self) -> None:
        self.assertEqual(
            canonical_news_url("https://finance.yahoo.co.jp/news/detail/abc123?utm_source=x#body"),
            "https://finance.yahoo.co.jp/news/detail/abc123",
        )


if __name__ == "__main__":
    unittest.main()
