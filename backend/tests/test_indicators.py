from __future__ import annotations

import unittest

from backend.app.services.indicators import calculate_indicator_rows


class IndicatorCalculationTest(unittest.TestCase):
    def test_calculates_latest_features_without_lookahead(self) -> None:
        rows = []
        for day in range(1, 81):
            rows.append(
                {
                    "company_id": 1,
                    "timeframe": "1d",
                    "date": f"2026-01-{day:02d}",
                    "open": float(day + 99),
                    "high": float(day + 102),
                    "low": float(day + 98),
                    "close": float(day + 100),
                    "volume": float(day * 100),
                }
            )

        indicators = calculate_indicator_rows(rows)
        latest = indicators[-1]

        self.assertEqual(latest["ma_5"], 178.0)
        self.assertEqual(latest["ma_25"], 168.0)
        self.assertEqual(latest["ma_75"], 143.0)
        self.assertEqual(latest["trend_short"], "up")
        self.assertEqual(latest["trend_middle"], "up")
        self.assertEqual(latest["recent_high_break"], 1)
        self.assertEqual(latest["recent_low_break"], 0)

    def test_marks_insufficient_history_as_none(self) -> None:
        rows = [
            {
                "company_id": 1,
                "timeframe": "1d",
                "date": "2026-01-01",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000.0,
            }
        ]
        indicators = calculate_indicator_rows(rows)
        self.assertIsNone(indicators[0]["ma_5"])
        self.assertEqual(indicators[0]["trend_short"], "unknown")


if __name__ == "__main__":
    unittest.main()
