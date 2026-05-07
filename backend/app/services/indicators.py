from __future__ import annotations

import json
import math
import sqlite3
from statistics import mean, pstdev
from typing import Any

from ..database import utc_now


def _avg(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) != len(values) or not clean:
        return None
    return float(mean(clean))


def _window_avg(values: list[float | None], end_index: int, window: int) -> float | None:
    if end_index + 1 < window:
        return None
    return _avg(values[end_index - window + 1 : end_index + 1])


def _pct_change(values: list[float | None], end_index: int, periods: int) -> float | None:
    if end_index < periods:
        return None
    current = values[end_index]
    previous = values[end_index - periods]
    if current is None or previous in (None, 0):
        return None
    return (float(current) / float(previous) - 1.0) * 100.0


def _rsi(closes: list[float | None], end_index: int, window: int = 14) -> float | None:
    if end_index < window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(end_index - window + 1, end_index + 1):
        current = closes[idx]
        previous = closes[idx - 1]
        if current is None or previous is None:
            return None
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _volatility(closes: list[float | None], end_index: int, window: int = 20) -> float | None:
    if end_index < window:
        return None
    returns: list[float] = []
    for idx in range(end_index - window + 1, end_index + 1):
        current = closes[idx]
        previous = closes[idx - 1]
        if current is None or previous in (None, 0):
            return None
        returns.append(math.log(float(current) / float(previous)))
    return float(pstdev(returns))


def _trend(close: float | None, short_ma: float | None, long_ma: float | None) -> str:
    if close is None or short_ma is None or long_ma is None:
        return "unknown"
    if close >= short_ma >= long_ma:
        return "up"
    if close <= short_ma <= long_ma:
        return "down"
    return "neutral"


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _pct_vs(value: float | None, base: float | None) -> float | None:
    if value is None or base in (None, 0):
        return None
    return (float(value) / float(base) - 1.0) * 100.0


def _round(value: Any, digits: int = 4) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def calculate_indicator_rows(price_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calculate one technical indicator row per OHLCV row.

    The input must be sorted ascending by date. All calculations are historical
    and use only data available at each target row.
    """
    closes = [row.get("close") for row in price_rows]
    highs = [row.get("high") for row in price_rows]
    lows = [row.get("low") for row in price_rows]
    opens = [row.get("open") for row in price_rows]
    volumes = [row.get("volume") for row in price_rows]
    indicator_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(price_rows):
        close = closes[idx]
        volume = volumes[idx]
        ma_5 = _window_avg(closes, idx, 5)
        ma_25 = _window_avg(closes, idx, 25)
        ma_75 = _window_avg(closes, idx, 75)
        volume_ma_5 = _window_avg(volumes, idx, 5)
        volume_ma_25 = _window_avg(volumes, idx, 25)
        recent_high_break = None
        recent_low_break = None
        if idx >= 20 and highs[idx] is not None and lows[idx] is not None:
            previous_highs = [value for value in highs[idx - 20 : idx] if value is not None]
            previous_lows = [value for value in lows[idx - 20 : idx] if value is not None]
            if previous_highs:
                recent_high_break = int(float(highs[idx]) >= max(previous_highs))
            if previous_lows:
                recent_low_break = int(float(lows[idx]) <= min(previous_lows))

        gap_up = None
        gap_down = None
        if idx >= 1 and opens[idx] is not None and highs[idx - 1] is not None and lows[idx - 1] is not None:
            gap_up = int(float(opens[idx]) > float(highs[idx - 1]))
            gap_down = int(float(opens[idx]) < float(lows[idx - 1]))

        features = {
            "last_close": close,
            "change_1d_pct": _pct_change(closes, idx, 1),
            "change_5d_pct": _pct_change(closes, idx, 5),
            "change_20d_pct": _pct_change(closes, idx, 20),
            "ma_5": ma_5,
            "ma_25": ma_25,
            "ma_75": ma_75,
            "price_vs_ma_5_pct": _pct_vs(close, ma_5),
            "price_vs_ma_25_pct": _pct_vs(close, ma_25),
            "price_vs_ma_75_pct": _pct_vs(close, ma_75),
            "volume_ratio_5d": _ratio(volume, volume_ma_5),
            "volatility_20d": _volatility(closes, idx, 20),
            "trend_short": _trend(close, ma_5, ma_25),
            "trend_middle": _trend(close, ma_25, ma_75),
            "recent_high_break": bool(recent_high_break) if recent_high_break is not None else None,
            "recent_low_break": bool(recent_low_break) if recent_low_break is not None else None,
            "gap_up": bool(gap_up) if gap_up is not None else None,
            "gap_down": bool(gap_down) if gap_down is not None else None,
        }
        features = {key: _round(value) for key, value in features.items()}
        indicator_rows.append(
            {
                "company_id": row["company_id"],
                "timeframe": row["timeframe"],
                "date": row["date"],
                "ma_5": _round(ma_5),
                "ma_25": _round(ma_25),
                "ma_75": _round(ma_75),
                "volume_ma_5": _round(volume_ma_5),
                "volume_ma_25": _round(volume_ma_25),
                "rsi_14": _round(_rsi(closes, idx, 14)),
                "volatility_20": _round(features["volatility_20d"]),
                "trend_short": features["trend_short"],
                "trend_middle": features["trend_middle"],
                "recent_high_break": recent_high_break,
                "recent_low_break": recent_low_break,
                "gap_up": gap_up,
                "gap_down": gap_down,
                "features_json": json.dumps(features, ensure_ascii=False),
            }
        )

    return indicator_rows


def calculate_for_company(
    conn: sqlite3.Connection,
    company_id: int,
    timeframe: str = "1d",
) -> int:
    price_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT company_id, timeframe, date, open, high, low, close, volume
            FROM price_bars
            WHERE company_id = ? AND timeframe = ?
            ORDER BY date ASC
            """,
            (company_id, timeframe),
        ).fetchall()
    ]
    if not price_rows:
        return 0

    indicator_rows = calculate_indicator_rows(price_rows)
    now = utc_now()
    for row in indicator_rows:
        conn.execute(
            """
            INSERT INTO technical_indicators (
                company_id, timeframe, date, ma_5, ma_25, ma_75,
                volume_ma_5, volume_ma_25, rsi_14, volatility_20,
                trend_short, trend_middle, recent_high_break, recent_low_break,
                gap_up, gap_down, features_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, timeframe, date) DO UPDATE SET
                ma_5 = excluded.ma_5,
                ma_25 = excluded.ma_25,
                ma_75 = excluded.ma_75,
                volume_ma_5 = excluded.volume_ma_5,
                volume_ma_25 = excluded.volume_ma_25,
                rsi_14 = excluded.rsi_14,
                volatility_20 = excluded.volatility_20,
                trend_short = excluded.trend_short,
                trend_middle = excluded.trend_middle,
                recent_high_break = excluded.recent_high_break,
                recent_low_break = excluded.recent_low_break,
                gap_up = excluded.gap_up,
                gap_down = excluded.gap_down,
                features_json = excluded.features_json,
                updated_at = excluded.updated_at
            """,
            (
                row["company_id"],
                row["timeframe"],
                row["date"],
                row["ma_5"],
                row["ma_25"],
                row["ma_75"],
                row["volume_ma_5"],
                row["volume_ma_25"],
                row["rsi_14"],
                row["volatility_20"],
                row["trend_short"],
                row["trend_middle"],
                row["recent_high_break"],
                row["recent_low_break"],
                row["gap_up"],
                row["gap_down"],
                row["features_json"],
                now,
                now,
            ),
        )
    return len(indicator_rows)


def calculate_for_all_companies(conn: sqlite3.Connection, timeframe: str = "1d") -> int:
    company_rows = conn.execute("SELECT id FROM companies WHERE is_active = 1").fetchall()
    return sum(calculate_for_company(conn, int(row["id"]), timeframe) for row in company_rows)
