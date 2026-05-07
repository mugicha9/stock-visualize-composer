from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from backend.app.models import BacktestRequest
from backend.app.services.backtests import _decision_indices, run_backtest
from backend.app.services.company_sources import _split_news_text
from backend.app.services.content_summaries import _extract_article_text, _format_summary
from backend.app.services.features import build_llm_input
from backend.app.services.information_dates import refresh_information_dates
from backend.app.services.judgements import get_judgement_context
from backend.app.services.llm import MockProvider, _grounding_issues, _repair_grounding_output
from backend.app.services.company_news_profile import fallback_company_news_profile, score_company_news_candidate
from backend.app.services.signal_pipeline import (
    build_context_packet,
    build_final_judgement_input,
    format_context_packet_markdown,
)


class BacktestLeakageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        schema = Path("backend/app/schema.sql").read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self._seed_company()

    def tearDown(self) -> None:
        self.conn.close()

    def test_build_llm_input_filters_future_context_by_as_of(self) -> None:
        self._seed_context()
        refresh_information_dates(self.conn)

        payload = build_llm_input(self.conn, "7203", as_of="2026-01-10")

        event_context = payload["event_context"]
        digest_titles = {item["title"] for item in event_context["news_digest"]["latest_items"]}
        fundamental_titles = {item["title"] for item in event_context["fundamental_digest"]["financial_disclosures"]}
        news_titles = {item["title"] for item in event_context["recent_news_candidates"]}
        disclosure_titles = {item["title"] for item in event_context["recent_disclosures"]}
        external_titles = {item["title"] for item in event_context["selected_global_news"]}

        self.assertEqual(payload["as_of"], "2026-01-10")
        self.assertIn("past news 上方修正", news_titles)
        self.assertIn("url dated news", news_titles)
        self.assertNotIn("future news", news_titles)
        self.assertNotIn("future url dated news", news_titles)
        self.assertIn("past news 上方修正", digest_titles)
        self.assertIn("url dated news", digest_titles)
        self.assertNotIn("future news", digest_titles)
        self.assertNotIn("future url dated news", digest_titles)
        self.assertIn("past disclosure 決算短信", fundamental_titles)
        self.assertNotIn("future disclosure 決算短信", fundamental_titles)
        self.assertIn("past disclosure 決算短信", disclosure_titles)
        self.assertNotIn("future disclosure 決算短信", disclosure_titles)
        self.assertIn("past factor", external_titles)
        self.assertNotIn("future factor", external_titles)
        self.assertEqual(event_context["latest_financial_snapshot"]["as_of"], "2026-01-09")
        self.assertEqual(event_context["fundamental_digest"]["snapshot"]["metrics"]["per"]["value"], "10.5")
        self.assertEqual(event_context["fundamental_digest"]["opportunity"]["level"], "strong_value_dislocation")

    def test_backtest_executes_signal_on_next_open(self) -> None:
        self._seed_prompt()
        self._insert_price("2026-01-10", 100, 101, 99, 100)
        self._insert_price("2026-01-11", 110, 112, 108, 111)
        self._insert_price("2026-01-12", 120, 122, 119, 121)
        self._insert_indicator("2026-01-10")
        self._insert_financial_snapshot("2026-01-10")

        result = run_backtest(
            self.conn,
            BacktestRequest(
                security_code="7203",
                start_date="2026-01-10",
                end_date="2026-01-12",
                interval="1d",
                provider="mock",
                max_steps=1,
            ),
        )

        self.assertEqual(result["decisions"][0]["action"], "BUY")
        self.assertEqual(result["decisions"][0]["next_execution_date"], "2026-01-11")
        self.assertEqual(result["decisions"][0]["next_execution_price"], 110)
        self.assertEqual(result["trades"][0]["entry_price"], 110)
        self.assertAlmostEqual(result["summary"]["total_return_pct"], 10.0)

    def test_decision_indices_support_slower_intervals(self) -> None:
        bars = [{"date": f"2026-01-{day:02d}"} for day in range(1, 32)] + [{"date": "2026-02-01"}, {"date": "2026-02-02"}]

        two_week_dates = [bars[index]["date"] for index in _decision_indices(bars, "2w")]
        monthly_dates = [bars[index]["date"] for index in _decision_indices(bars, "1mo")]

        self.assertEqual(two_week_dates, ["2026-01-01", "2026-01-15", "2026-01-29"])
        self.assertEqual(monthly_dates, ["2026-01-01", "2026-02-01"])

    def test_mock_keeps_value_opportunity_when_technicals_are_weak(self) -> None:
        output = MockProvider().generate(
            "test",
            {
                "price_features": {
                    "trend_short": "down",
                    "trend_middle": "down",
                    "recent_low_break": True,
                    "price_vs_ma_25_pct": -8,
                    "volume_ratio_5d": 1.1,
                },
                "event_context": {
                    "fundamental_digest": {
                        "opportunity": {
                            "level": "strong_value_dislocation",
                            "decision_bias": "technical_weakness_can_be_opportunity",
                            "signals": ["PBRが1倍以下で、純資産対比の価値乖離候補です。", "ROEが高く、資本効率は価値評価の支援材料です。"],
                            "risks": [],
                        }
                    },
                    "fundamental_context": {},
                },
                "data_quality": {"warnings": []},
            },
        )

        self.assertEqual(output["action"], "WATCH_BUY")
        self.assertIn("価値乖離", output["summary"])

    def test_signal_pipeline_builds_context_packet_without_raw_bulk(self) -> None:
        self._seed_context()
        refresh_information_dates(self.conn)
        payload = build_llm_input(self.conn, "7203", as_of="2026-01-10")
        payload["event_context"]["news_digest"]["latest_items"] = [
            {
                "type": "company_news",
                "date": "2026-01-10",
                "title": f"news {index}",
                "summary": "長い本文" * 120,
                "url": f"https://example.test/{index}",
            }
            for index in range(20)
        ]

        context_packet = build_context_packet(payload)
        signal_cards = context_packet["signal_cards"]
        source_types = {card["source_type"] for card in signal_cards}

        self.assertEqual(context_packet["company"]["security_code"], "7203")
        self.assertIn("technical", source_types)
        self.assertIn("fundamental", source_types)
        self.assertLessEqual(len(signal_cards), 14)
        self.assertEqual(context_packet["aggregated_signal"]["overall_bias"], "bullish")
        self.assertEqual(context_packet["aggregated_signal"]["weights"]["technical"], 0.2)

    def test_context_packet_markdown_surfaces_fundamentals_and_news(self) -> None:
        self._seed_context()
        refresh_information_dates(self.conn)
        payload = build_llm_input(self.conn, "7203", as_of="2026-01-10")
        context_packet = build_context_packet(payload)

        markdown = format_context_packet_markdown(context_packet)

        self.assertIn("## Fundamental Summary", markdown)
        self.assertIn("## Signal Cards", markdown)
        self.assertIn("PER", markdown)
        self.assertIn("10.5倍", markdown)
        self.assertIn("## Company Profile", markdown)
        self.assertIn("主力/関連テーマ", markdown)
        self.assertIn("past disclosure 決算短信", markdown)
        self.assertIn("past news 上方修正", markdown)

    def test_signal_cards_display_llm_summary_not_raw_news_category(self) -> None:
        self._seed_context()
        refresh_information_dates(self.conn)
        payload = build_llm_input(self.conn, "7203", as_of="2026-01-10")
        payload["event_context"]["news_digest"]["latest_items"] = [
            {
                "type": "global_news",
                "date": "2026-01-10",
                "age_days": 0,
                "category": "macro_policy",
                "title": "規制改革の議論が進む",
                "summary": "分類: 規制・政策 要約: 規制改革の議論が企業活動へ影響する可能性があります。 要点: 規制改革 / 事業環境 注意: 企業ごとの影響度は未確定 材料性: 中立 根拠: 本文",
                "relevance_score": 1.0,
            }
        ]

        context_packet = build_context_packet(payload)
        cards_text = json.dumps(context_packet["signal_cards"], ensure_ascii=False)

        self.assertNotIn("macro_policy", cards_text)
        self.assertIn("LLM分類: 規制・政策", cards_text)
        self.assertIn("記事要約: 規制改革の議論が企業活動へ影響する可能性があります。", cards_text)

    def test_judgement_context_rebuilds_signal_cards_from_saved_input(self) -> None:
        self._seed_context()
        refresh_information_dates(self.conn)
        payload = build_llm_input(self.conn, "7203", as_of="2026-01-10")
        output = {
            "judgement_type": "mid_long_term",
            "action": "WATCH_BUY",
            "confidence": 0.6,
            "time_horizon": "3_months_to_1_year",
            "summary": "ファンダメンタルとニュースを確認しながら監視する局面です。",
            "positive_factors": ["PERとPBRに過度な割高感はありません。"],
            "negative_factors": ["出来高の裏付けはまだ限定的です。"],
            "entry_conditions": ["出来高増加を確認します。"],
            "exit_conditions": ["収益性の悪化が確認された場合は撤退します。"],
            "risk_notes": ["外部環境の変化に注意します。"],
        }
        cur = self.conn.execute(
            """
            INSERT INTO ai_judgements
                (company_id, judgement_type, target_date, action, confidence, time_horizon,
                 input_json, output_json, model_provider, model_name, model_options_json, data_as_of, created_at)
            VALUES (1, 'mid_long_term', '2026-01-10', 'WATCH_BUY', 0.6, '3_months_to_1_year',
                    ?, ?, 'mock', 'mock', '{}', '2026-01-10', '2026-01-10')
            """,
            (json.dumps(payload, ensure_ascii=False), json.dumps(output, ensure_ascii=False)),
        )

        context = get_judgement_context(self.conn, int(cur.lastrowid))

        self.assertTrue(context["generated_from_saved_input"])
        self.assertIn("context_packet", context)
        self.assertGreater(context["card_counts"].get("fundamental", 0), 0)
        self.assertGreater(len(context["context_packet"]["signal_cards"]), 0)
        self.assertGreater(len(context["source_items"]["news_digest_items"]), 0)

    def test_final_judgement_input_contains_context_packet_only(self) -> None:
        self._seed_context()
        refresh_information_dates(self.conn)
        payload = build_llm_input(self.conn, "7203", as_of="2026-01-10")

        model_input = build_final_judgement_input(payload)

        self.assertIn("context_packet", model_input)
        self.assertIn("signal_cards", model_input["context_packet"])
        self.assertIn("company_profile", model_input["context_packet"])
        self.assertIn("Auto", model_input["context_packet"]["company_profile"]["business_terms"])
        self.assertIn("company_profile", model_input["rules"]["must_consider"])
        self.assertNotIn("recent_news", model_input["context_packet"])

    def test_grounding_uses_context_packet_evidence(self) -> None:
        context_packet = {
            "data_status": {"missing_data": []},
            "signal_cards": [
                {
                    "source_type": "fundamental",
                    "summary": "業績予想修正に関連する開示です。",
                    "evidence": ["業績予想修正に関連する開示: 配当予想の修正に関するお知らせ"],
                    "risk_notes": [],
                }
            ],
        }
        output = {
            "action": "WATCH_BUY",
            "confidence": 0.5,
            "summary": "業績予想修正に関連する開示を確認します。",
            "positive_factors": ["業績予想修正の開示があります。"],
            "negative_factors": ["方向性は未確認です。"],
            "entry_conditions": ["出来高を確認します。"],
            "exit_conditions": ["25日線を下回る場合。"],
            "risk_notes": ["好材料とは断定しません。"],
        }

        self.assertEqual(_grounding_issues(output, context_packet), [])

    def test_grounding_allows_schema_enum_codes(self) -> None:
        context_packet = {"data_status": {"missing_data": []}, "signal_cards": []}
        output = {
            "judgement_type": "mid_long_term",
            "action": "WATCH_BUY",
            "confidence": 0.5,
            "time_horizon": "3_months_to_1_year",
            "summary": "ファンダメンタルとニュースを確認しながら監視する局面です。",
            "positive_factors": ["PERとPBRに過度な割高感はありません。"],
            "negative_factors": ["出来高の裏付けはまだ限定的です。"],
            "entry_conditions": ["25日線を回復し、出来高が増加することを確認します。"],
            "exit_conditions": ["決算または開示で収益性の悪化が確認された場合は撤退します。"],
            "risk_notes": ["外部環境の変化で評価が変わる可能性があります。"],
            "used_signal_types": ["technical", "fundamental", "news", "market"],
        }

        self.assertNotIn("英語文の混入", _grounding_issues(output, context_packet))

    def test_grounding_detects_english_sentence_in_explanation(self) -> None:
        context_packet = {"data_status": {"missing_data": []}, "signal_cards": []}
        output = {
            "judgement_type": "mid_long_term",
            "action": "NO_TRADE",
            "confidence": 0.5,
            "time_horizon": "3_months_to_1_year",
            "summary": "Technical trend is improving but fundamentals remain unclear.",
            "positive_factors": ["PERは過度な割高感を示していません。"],
            "negative_factors": ["出来高の裏付けはまだ限定的です。"],
            "entry_conditions": ["25日線を回復し、出来高が増加することを確認します。"],
            "exit_conditions": ["収益性の悪化が確認された場合は撤退します。"],
            "risk_notes": ["外部環境の変化で評価が変わる可能性があります。"],
            "used_signal_types": ["technical", "fundamental"],
        }

        self.assertIn("英語文の混入", _grounding_issues(output, context_packet))

    def test_invalid_news_date_fragment_does_not_break_parsing(self) -> None:
        parsed = _split_news_text("決算発表予定 (27/5～1/6)19:00株探ニュース")

        self.assertEqual(parsed["title"], "決算発表予定 (")
        self.assertIsNone(parsed["published_at"])

    def test_article_summary_helpers_compress_news_text(self) -> None:
        text = _extract_article_text(
            """
            <html><body><script>ignore()</script>
            <article><p>会社は中期計画で営業利益率の改善を示した。</p>
            <p>一方で原材料価格の上昇には注意が必要。</p></article></body></html>
            """
        )
        summary = _format_summary(
            {
                "topic": "決算・業績",
                "summary": "中期計画で営業利益率改善を示した。",
                "materiality": "positive",
                "key_points": ["営業利益率改善", "中期計画"],
                "risk_notes": ["原材料価格上昇"],
                "source_basis": "本文",
            }
        )

        self.assertIn("営業利益率", text or "")
        self.assertIn("分類: 決算・業績", summary)
        self.assertIn("要点", summary)
        self.assertIn("材料性: ポジティブ", summary)

    def test_grounding_repair_removes_unbacked_revision_terms(self) -> None:
        context_packet = {"data_status": {"missing_data": []}, "signal_cards": []}
        output = {
            "judgement_type": "mid_long_term",
            "action": "WATCH_BUY",
            "confidence": 0.5,
            "time_horizon": "3_months_to_1_year",
            "summary": "上方修正を根拠に監視します。",
            "positive_factors": ["上方修正が支援材料です。"],
            "negative_factors": ["短期の値動きは不安定です。"],
            "entry_conditions": ["出来高を確認します。"],
            "exit_conditions": ["業績修正が悪化した場合。"],
            "risk_notes": ["入力にない材料は確認が必要です。"],
        }

        issues = _grounding_issues(output, context_packet)
        repaired = _repair_grounding_output(output, issues, context_packet)

        self.assertIn("未入力の業績修正", issues)
        self.assertEqual(_grounding_issues(repaired, context_packet), [])

    def test_company_news_profile_keeps_related_material_news(self) -> None:
        company = {"id": 1, "security_code": "7011", "name": "三菱重工業", "industry": "機械"}
        profile = fallback_company_news_profile(company)

        result = score_company_news_candidate(
            {"title": "三菱重工、防衛関連で大型受注", "provider": "ロイター"},
            company,
            profile,
        )

        self.assertTrue(result["keep"])
        self.assertGreaterEqual(result["score"], 0.35)

    def test_company_news_profile_drops_unrelated_recurring_news(self) -> None:
        company = {"id": 1, "security_code": "7011", "name": "三菱重工業", "industry": "機械"}
        profile = fallback_company_news_profile(company)

        result = score_company_news_candidate(
            {"title": "前日に動いた株、低PBR銘柄ランキング", "provider": "株探"},
            company,
            profile,
        )

        self.assertFalse(result["keep"])

    def test_company_news_profile_drops_other_company_news(self) -> None:
        company = {"id": 1, "security_code": "7011", "name": "三菱重工業", "industry": "機械"}
        profile = fallback_company_news_profile(company)

        result = score_company_news_candidate(
            {"title": "トヨタ、通期業績予想を上方修正", "provider": "ロイター"},
            company,
            profile,
        )

        self.assertFalse(result["keep"])

    def _seed_company(self) -> None:
        self.conn.execute(
            """
            INSERT INTO companies
                (id, security_code, name, market, sector, industry, is_active, created_at, updated_at)
            VALUES (1, '7203', 'Toyota', 'Prime', 'Automobiles', 'Auto', 1, '2026-01-01', '2026-01-01')
            """
        )

    def _seed_prompt(self) -> None:
        self.conn.execute(
            """
            INSERT INTO ai_prompt_templates
                (name, judgement_type, version, template_text, model_name, is_active, created_at)
            VALUES ('test', 'short_term', 'v1', 'test prompt', 'mock', 1, '2026-01-01')
            """
        )

    def _insert_financial_snapshot(self, as_of: str) -> None:
        self.conn.execute(
            """
            INSERT INTO company_financials
                (company_id, source, as_of, fiscal_period, next_earnings_date, summary, metrics_json, created_at, updated_at)
            VALUES (
                1,
                'test',
                ?,
                'Q3',
                '2026-02-01',
                'financials',
                '{"per": {"name": "PER", "value": "10.5", "suffix": "倍"}, "pbr": {"name": "PBR", "value": "0.9", "suffix": "倍"}, "roe": {"name": "ROE", "value": "12", "suffix": "%"}}',
                ?,
                ?
            )
            """,
            (as_of, as_of, as_of),
        )

    def _seed_context(self) -> None:
        self._insert_price("2026-01-09", 99, 101, 98, 100)
        self._insert_price("2026-01-10", 100, 102, 99, 101)
        self._insert_price("2026-01-11", 101, 103, 100, 102)
        self._insert_indicator("2026-01-10")
        self.conn.execute(
            """
            INSERT INTO company_financials
                (company_id, source, as_of, fiscal_period, next_earnings_date, summary, metrics_json, created_at, updated_at)
            VALUES (
                1,
                'test',
                '2026-01-09',
                'Q3',
                '2026-02-01',
                'past financials',
                '{"per": {"name": "PER", "value": "10.5", "suffix": "倍"}, "pbr": {"name": "PBR", "value": "0.9", "suffix": "倍"}, "roe": {"name": "ROE", "value": "12", "suffix": "%"}, "equity_ratio": {"name": "自己資本比率", "value": "50", "suffix": "%"}}',
                '2026-01-09',
                '2026-01-09'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO company_financials
                (company_id, source, as_of, fiscal_period, next_earnings_date, summary, metrics_json, created_at, updated_at)
            VALUES (1, 'test', '2026-01-11', 'Q4', '2026-03-01', 'future financials', '{}', '2026-01-11', '2026-01-11')
            """
        )
        self.conn.execute(
            """
            INSERT INTO news_articles
                (company_id, title, published_at, source, provider, url, summary, created_at, updated_at)
            VALUES
                (1, 'past news 上方修正', '2026-01-10', 'test', 'test', 'https://example.test/past-news', '', '2026-01-10', '2026-01-10'),
                (1, 'future news', '2026-01-11', 'test', 'test', 'https://example.test/future-news', '', '2026-01-11', '2026-01-11'),
                (1, 'url dated news', NULL, 'test', 'test', 'https://example.test/news/20260109/url-dated-news', '', '2026-01-12', '2026-01-12'),
                (1, 'future url dated news', NULL, 'test', 'test', 'https://example.test/news/20260111/future-url-dated-news', '', '2026-01-12', '2026-01-12')
            """
        )
        self.conn.execute(
            """
            INSERT INTO disclosures
                (company_id, title, document_type, published_at, source, url, summary, importance_score, created_at, updated_at)
            VALUES
                (1, 'past disclosure 決算短信', 'tdnet', '2026-01-10', 'test', 'https://example.test/past-disclosure', '', 0.5, '2026-01-10', '2026-01-10'),
                (1, 'future disclosure 決算短信', 'tdnet', '2026-01-11', 'test', 'https://example.test/future-disclosure', '', 0.5, '2026-01-11', '2026-01-11')
            """
        )
        self.conn.execute(
            """
            INSERT INTO global_news
                (category, title, published_at, source, provider, url, summary, created_at, updated_at)
            VALUES
                ('policy', 'past factor', '2026-01-10', 'test', 'test', 'https://example.test/past-factor', '', '2026-01-10', '2026-01-10'),
                ('policy', 'future factor', '2026-01-11', 'test', 'test', 'https://example.test/future-factor', '', '2026-01-11', '2026-01-11')
            """
        )

    def _insert_price(self, price_date: str, open_: float, high: float, low: float, close: float) -> None:
        self.conn.execute(
            """
            INSERT INTO price_bars
                (company_id, timeframe, date, open, high, low, close, volume, source, created_at, updated_at)
            VALUES (1, '1d', ?, ?, ?, ?, ?, 1000, 'test', ?, ?)
            """,
            (price_date, open_, high, low, close, price_date, price_date),
        )

    def _insert_indicator(self, indicator_date: str) -> None:
        features = {
            "last_close": 100,
            "change_1d_pct": 1,
            "change_5d_pct": 2,
            "change_20d_pct": 5,
            "ma_5": 100,
            "ma_25": 98,
            "ma_75": 96,
            "price_vs_ma_25_pct": 3,
            "volume_ratio_5d": 1.5,
            "volatility_20d": 0.1,
            "trend_short": "up",
            "trend_middle": "up",
            "recent_high_break": True,
            "recent_low_break": False,
        }
        self.conn.execute(
            """
            INSERT INTO technical_indicators
                (company_id, timeframe, date, ma_5, ma_25, ma_75, volume_ma_5, volume_ma_25,
                 trend_short, trend_middle, recent_high_break, recent_low_break, features_json,
                 created_at, updated_at)
            VALUES (1, '1d', ?, 100, 98, 96, 1000, 900, 'up', 'up', 1, 0, ?, ?, ?)
            """,
            (indicator_date, json.dumps(features), indicator_date, indicator_date),
        )


if __name__ == "__main__":
    unittest.main()
