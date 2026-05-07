from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


POSITIVE_TERMS = {
    "上方修正": 1.4,
    "増益": 1.0,
    "増収": 0.7,
    "最高益": 1.2,
    "増配": 1.0,
    "自社株買い": 1.0,
    "自己株式取得": 1.0,
    "好調": 0.6,
    "受注": 0.5,
    "提携": 0.5,
    "買収": 0.5,
    "新製品": 0.4,
}

NEGATIVE_TERMS = {
    "下方修正": -1.4,
    "減益": -1.0,
    "減収": -0.7,
    "赤字": -1.2,
    "減配": -1.0,
    "無配": -1.2,
    "損失": -0.8,
    "不正": -1.2,
    "訴訟": -0.8,
    "規制": -0.6,
    "原油高": -0.5,
    "コスト増": -0.5,
    "価格上昇": -0.35,
}

CATEGORY_KEYWORDS = [
    ("forecast_revision", ["上方修正", "下方修正", "業績予想", "通期予想", "予想修正"]),
    ("earnings", ["決算", "短信", "四半期", "営業利益", "経常利益", "純利益"]),
    ("dividend", ["配当", "増配", "減配", "無配"]),
    ("share_buyback", ["自己株式取得", "自社株買い"]),
    ("business_alliance", ["提携", "協業", "合弁"]),
    ("ma", ["買収", "M&A", "TOB"]),
    ("lawsuit", ["訴訟", "裁判"]),
    ("scandal", ["不正", "不祥事", "調査"]),
    ("regulation", ["規制", "行政処分", "関税"]),
    ("macro", ["為替", "金利", "原油", "ナフサ", "景気", "政策"]),
    ("industry", ["業界", "需要", "供給", "市況"]),
    ("analyst", ["レーティング", "目標株価"]),
]


def build_final_judgement_input(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "日本株の中長期売買判断を行ってください。",
        "rules": {
            "allowed_actions": ["BUY", "WATCH_BUY", "NO_TRADE", "WATCH_SELL", "SELL", "INSUFFICIENT_DATA"],
            "time_horizon": "3_months_to_1_year",
            "must_consider": [
                "company_profile",
                "technical_summary",
                "news_summary",
                "fundamental_summary",
                "data_status",
                "aggregated_signal",
            ],
            "do_not": [
                "入力にない事実を作らない",
                "Context Packetにない長期予測を作らない",
                "リアルタイム株価がある前提で判断しない",
                "根拠が弱いのにBUYまたはSELLを出さない",
                "signal_cardsに存在しないsignal_idをused_signal_idsに入れない",
            ],
            "used_signal_ids_rule": "判断に使ったsignal_cardsのsignal_idをused_signal_idsへ必ず入れる。",
            "output_language": "ja",
        },
        "context_packet": build_context_packet(payload),
    }


def build_context_packet(payload: dict[str, Any]) -> dict[str, Any]:
    company = payload.get("company") or {}
    company_profile = company.get("business_profile") or (payload.get("event_context") or {}).get("company_business_profile") or {}
    cards = build_signal_cards(payload)
    technical_cards = [card for card in cards if card["source_type"] == "technical"]
    news_cards = [card for card in cards if card["source_type"] == "news"]
    fundamental_cards = [card for card in cards if card["source_type"] == "fundamental"]
    market_cards = [card for card in cards if card["source_type"] == "market"]
    aggregated = _aggregate(cards, payload)

    return {
        "company": company,
        "company_profile": company_profile,
        "as_of": payload.get("as_of"),
        "judgement_type": "mid_long_term",
        "time_horizon": "3_months_to_1_year",
        "data_status": _data_status(payload, cards),
        "technical_summary": _summary_block(technical_cards),
        "news_summary": _summary_block(news_cards + market_cards),
        "fundamental_summary": _summary_block(fundamental_cards),
        "aggregated_signal": aggregated,
        "signal_cards": _top_cards(cards, 14),
    }


def build_signal_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    technical = _technical_signal(payload)
    if technical:
        cards.append(technical)
    cards.extend(_fundamental_signals(payload))
    cards.extend(_news_and_market_signals(payload))
    return cards


def format_context_packet_markdown(context_packet: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            "## Context Packet",
            _table(["項目", "値"], _packet_rows(context_packet)),
            "## Company Profile",
            _table(["項目", "値"], _company_profile_rows(context_packet.get("company_profile") or {})),
            "## Aggregated Signal",
            _table(["項目", "値"], [[key, value] for key, value in (context_packet.get("aggregated_signal") or {}).items()]),
            "## Technical Summary",
            _summary_table(context_packet.get("technical_summary") or {}),
            "## News / Market Summary",
            _summary_table(context_packet.get("news_summary") or {}),
            "## Fundamental Summary",
            _summary_table(context_packet.get("fundamental_summary") or {}),
            "## Signal Cards",
            _table(
                ["種別", "方向", "方向スコア", "影響度", "鮮度", "公開日", "要約", "根拠"],
                [
                    [
                        card.get("source_type"),
                        card.get("direction"),
                        card.get("direction_score"),
                        card.get("impact_score"),
                        card.get("freshness_score"),
                        card.get("published_at"),
                        card.get("summary"),
                        " / ".join(card.get("evidence") or []),
                    ]
                    for card in context_packet.get("signal_cards") or []
                ],
            ),
        ]
    )


def _technical_signal(payload: dict[str, Any]) -> dict[str, Any] | None:
    features = payload.get("price_features") or {}
    if not features:
        return None

    score = 0.0
    evidence: list[str] = []
    risks: list[str] = []
    trend_short = features.get("trend_short")
    trend_middle = features.get("trend_middle")
    volume_ratio = _num(features.get("volume_ratio_5d"))
    change_20d = _num(features.get("change_20d_pct"))
    change_5d = _num(features.get("change_5d_pct"))
    price_vs_ma25 = _num(features.get("price_vs_ma_25_pct"))

    if trend_short == "up":
        score += 0.35
        evidence.append("短期トレンドは上向きで、中長期判断の確認材料です。")
    elif trend_short == "down":
        score -= 0.35
        evidence.append("短期トレンドは下向きで、エントリー時期には慎重さが必要です。")

    if trend_middle == "up":
        score += 0.55
        evidence.append("中期トレンドが上向きです。")
    elif trend_middle == "down":
        score -= 0.55
        evidence.append("中期トレンドが下向きです。")

    if price_vs_ma25 is not None:
        if price_vs_ma25 > 0:
            score += min(price_vs_ma25 / 20, 0.45)
            evidence.append(f"株価は25日移動平均を{price_vs_ma25:.1f}%上回っています。")
        elif price_vs_ma25 < 0:
            score += max(price_vs_ma25 / 20, -0.45)
            evidence.append(f"株価は25日移動平均を{abs(price_vs_ma25):.1f}%下回っています。")

    if volume_ratio is not None:
        if volume_ratio >= 1.2:
            score += 0.35
            evidence.append(f"出来高は5日平均比{volume_ratio:.2f}倍です。")
        elif volume_ratio < 0.6:
            score -= 0.2
            risks.append(f"出来高は5日平均比{volume_ratio:.2f}倍で、売買の裏付けは弱いです。")

    if features.get("recent_high_break"):
        score += 0.45
        evidence.append("直近高値を更新しています。")
    if features.get("recent_low_break"):
        score -= 0.55
        evidence.append("直近安値を更新しています。")

    if change_5d is not None and change_5d <= -5:
        risks.append(f"5日騰落率が{change_5d:.1f}%で、買い付けタイミングには注意が必要です。")
    if change_20d is not None and change_20d >= 15:
        score -= 0.15
        risks.append(f"20日騰落率が{change_20d:.1f}%で、エントリー時点の過熱感があります。")

    score = _clamp(score, -2.0, 2.0)
    return _signal_card(
        payload,
        index=1,
        source_type="technical",
        source_name="technical_indicators",
        published_at=payload.get("as_of"),
        direction_score=score,
        impact_score=0.65,
        confidence=0.75 if evidence else 0.4,
        freshness_score=_freshness((payload.get("data_quality") or {}).get("latest_price_age_days")),
        summary=_technical_summary(score, evidence, risks),
        evidence=evidence or ["テクニカル特徴量はありますが、明確な方向感は限定的です。"],
        risk_notes=risks or ["日次データであり、長期の業績変化は価格だけでは判断しません。"],
    )


def _fundamental_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    event_context = payload.get("event_context") or {}
    digest = event_context.get("fundamental_digest") or {}
    opportunity = digest.get("opportunity") or {}
    snapshot = digest.get("snapshot") or event_context.get("latest_financial_snapshot") or {}
    fundamental_context = event_context.get("fundamental_context") or {}
    disclosures = digest.get("financial_disclosures") or []
    if not digest and not snapshot and not fundamental_context:
        return []

    score = 0.0
    evidence: list[str] = []
    risks: list[str] = []
    level = opportunity.get("level")

    if level == "strong_value_dislocation":
        score += 1.2
        evidence.append("価値機会レベルはstrong_value_dislocationで、下落時の価値乖離候補です。")
    elif level == "moderate_value_support":
        score += 0.7
        evidence.append("価値機会レベルはmoderate_value_supportで、ファンダメンタルの下支えがあります。")
    elif level == "fundamental_risk":
        score -= 1.0
        risks.append("価値機会レベルはfundamental_riskで、ファンダメンタル悪化に注意が必要です。")

    for signal in opportunity.get("signals") or []:
        evidence.append(str(signal))
    for risk in opportunity.get("risks") or []:
        risks.append(str(risk))

    evidence.extend(_metric_evidence(snapshot))
    score += _context_score(fundamental_context, evidence, risks)
    disclosure_score, disclosure_evidence, disclosure_risks = _disclosure_score(disclosures)
    score += disclosure_score
    evidence.extend(disclosure_evidence)
    risks.extend(disclosure_risks)

    days_to_earnings = event_context.get("days_to_earnings")
    if days_to_earnings is None and isinstance(snapshot, dict):
        days_to_earnings = snapshot.get("days_to_earnings")
    if isinstance(days_to_earnings, int) and -3 <= days_to_earnings <= 14:
        risks.append(f"決算予定まで{days_to_earnings}日で、イベント通過前後の変動に注意が必要です。")

    score = _clamp(score, -2.0, 2.0)
    return [
        _signal_card(
            payload,
            index=1,
            source_type="fundamental",
            source_name=(snapshot or {}).get("source") or "company_financials",
            published_at=(snapshot or {}).get("as_of") or digest.get("as_of") or payload.get("as_of"),
            direction_score=score,
            impact_score=0.75 if disclosures else 0.55,
            confidence=0.78 if evidence or risks else 0.45,
            freshness_score=_freshness(_days_old((snapshot or {}).get("as_of"), payload.get("as_of"))),
            summary=_fundamental_summary(score, evidence, risks),
            evidence=evidence[:8] or ["財務・決算情報はありますが、方向感は限定的です。"],
            risk_notes=risks[:6] or ["ファンダメンタル情報は中長期判断の中心材料として扱います。"],
        )
    ]


def _news_and_market_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    event_context = payload.get("event_context") or {}
    latest_items = ((event_context.get("news_digest") or {}).get("latest_items") or [])[:18]
    cards: list[dict[str, Any]] = []
    for index, item in enumerate(latest_items, start=1):
        if not isinstance(item, dict):
            continue
        source_type = "market" if item.get("type") == "global_news" else "news"
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        text = f"{title} {summary}"
        llm_topic = _summary_field(summary, "分類")
        category = _topic_category(llm_topic) or _classify(text)
        assessment = item.get("material_assessment") if isinstance(item.get("material_assessment"), dict) else {}
        score = _assessment_score(assessment) if assessment else _keyword_score(text)
        impact = _impact_score(item, category, score, assessment)
        if impact < 0.3 and abs(score) < 0.25:
            continue
        evidence = [*_news_evidence(title, summary), *_keyword_evidence(text)]
        if assessment.get("reason"):
            evidence.insert(0, f"材料評価: {assessment.get('reason')}")
        for used in assessment.get("used_evidence") or []:
            evidence.append(f"評価根拠: {used}")
        if category == "forecast_revision":
            evidence.insert(0, "業績予想修正に関連する材料です。")
        confidence = _num(assessment.get("confidence")) if assessment else None
        extra = {
            "title": title,
            "source_event_id": item.get("source_event_id") or item.get("id"),
            "source_id": item.get("source_event_id") or item.get("id"),
        }
        if assessment:
            extra["material_assessment"] = assessment
        if llm_topic:
            extra["topic"] = llm_topic
        cards.append(
            _signal_card(
                payload,
                index=index,
                source_type=source_type,
                source_name=item.get("source") or item.get("provider") or item.get("type") or "news",
                published_at=item.get("date") or item.get("published_at"),
                direction_score=score,
                impact_score=impact,
                confidence=confidence if confidence is not None else (0.7 if evidence else 0.45),
                freshness_score=_freshness(item.get("age_days")),
                relevance_score=assessment.get("company_relevance") if assessment else (item.get("relevance_score") or 0.75),
                summary=_material_summary(score, title, summary, llm_topic, assessment),
                evidence=evidence or ([title] if title else ["ニュース材料の方向感は限定的です。"]),
                risk_notes=_material_risks(category, score, item, summary, assessment),
                extra=extra,
            )
        )
    return cards


def _aggregate(cards: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    technical_cards = [card for card in cards if card["source_type"] == "technical"]
    news_cards = [card for card in cards if card["source_type"] in {"news", "market"}]
    fundamental_cards = [card for card in cards if card["source_type"] == "fundamental"]

    technical_score = _weighted_average(technical_cards)
    news_score = _weighted_average(news_cards)
    fundamental_score = _weighted_average(fundamental_cards)
    weights = _weights(payload, news_cards, fundamental_cards)
    weighted_score = (
        technical_score * weights["technical"]
        + news_score * weights["news"]
        + fundamental_score * weights["fundamental"]
    )
    return {
        "technical_score": round(technical_score, 3),
        "news_score": round(news_score, 3),
        "fundamental_score": round(fundamental_score, 3),
        "weights": weights,
        "weighted_score": round(weighted_score, 3),
        "conflict_level": _conflict_level([technical_score, news_score, fundamental_score]),
        "overall_bias": _bias(weighted_score),
        "signal_count": len(cards),
    }


def _weights(payload: dict[str, Any], news_cards: list[dict[str, Any]], fundamental_cards: list[dict[str, Any]]) -> dict[str, float]:
    event_context = payload.get("event_context") or {}
    has_event = bool(fundamental_cards and any(card.get("impact_score", 0) >= 0.7 for card in fundamental_cards))
    has_event = has_event or bool(news_cards and any(card.get("impact_score", 0) >= 0.75 for card in news_cards))
    days_to_earnings = event_context.get("days_to_earnings")
    if isinstance(days_to_earnings, int) and -3 <= days_to_earnings <= 14:
        has_event = True
    if has_event:
        return {"technical": 0.20, "news": 0.35, "fundamental": 0.45}
    if not news_cards and not fundamental_cards:
        return {"technical": 0.40, "news": 0.20, "fundamental": 0.40}
    return {"technical": 0.25, "news": 0.25, "fundamental": 0.50}


def _summary_block(cards: list[dict[str, Any]]) -> dict[str, Any]:
    score = _weighted_average(cards)
    top = _top_cards(cards, 4)
    return {
        "direction_score": round(score, 3),
        "impact_score": round(max([card.get("impact_score", 0) for card in cards], default=0), 3),
        "summary": _joined_summary(top),
        "top_signals": top,
        "risk_notes": _unique([risk for card in top for risk in card.get("risk_notes") or []])[:6],
    }


def _data_status(payload: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, Any]:
    event_context = payload.get("event_context") or {}
    data_quality = payload.get("data_quality") or {}
    snapshot_value = (event_context.get("fundamental_digest") or {}).get("snapshot")
    snapshot = snapshot_value if isinstance(snapshot_value, dict) else {}
    warnings = list(data_quality.get("warnings") or [])
    if not cards:
        warnings.append("signal_cards_missing")
    return {
        "price_data_as_of": data_quality.get("latest_price_date"),
        "price_data_age_days": data_quality.get("latest_price_age_days"),
        "fundamental_data_as_of": snapshot.get("as_of"),
        "news_counts": (event_context.get("news_digest") or {}).get("counts") or {},
        "has_stale_data": "price_data_stale" in warnings,
        "missing_data": _unique(warnings),
    }


def _signal_card(
    payload: dict[str, Any],
    *,
    index: int,
    source_type: str,
    source_name: str,
    published_at: Any,
    direction_score: float,
    impact_score: float,
    confidence: float,
    freshness_score: float,
    summary: str,
    evidence: list[str],
    risk_notes: list[str],
    relevance_score: float = 1.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    company = payload.get("company") or {}
    security_code = str(company.get("security_code") or "unknown")
    direction = "bullish" if direction_score >= 0.35 else "bearish" if direction_score <= -0.35 else "neutral"
    card = {
        "signal_id": f"sig_{str(payload.get('as_of') or date.today().isoformat()).replace('-', '')}_{security_code}_{source_type}_{index:02d}",
        "company_code": security_code,
        "source_type": source_type,
        "source_name": source_name,
        "published_at": str(published_at) if published_at else None,
        "horizon": "mid_long_term",
        "direction": direction,
        "direction_score": round(_clamp(direction_score, -2.0, 2.0), 3),
        "impact_score": round(_clamp(impact_score, 0.0, 1.0), 3),
        "confidence": round(_clamp(confidence, 0.0, 1.0), 3),
        "freshness_score": round(_clamp(freshness_score, 0.0, 1.0), 3),
        "relevance_score": round(_clamp(_num(relevance_score) if _num(relevance_score) is not None else 1.0, 0.0, 1.0), 3),
        "summary": summary,
        "evidence": _unique([item for item in evidence if item])[:8],
        "risk_notes": _unique([item for item in risk_notes if item])[:6],
    }
    if extra:
        card.update(extra)
    return card


def _context_score(context: dict[str, Any], evidence: list[str], risks: list[str]) -> float:
    score = 0.0
    valuation = context.get("valuation") or {}
    profitability = context.get("profitability") or {}
    safety = context.get("financial_safety") or {}
    returns = context.get("shareholder_return") or {}

    if valuation.get("direction") == "undemanding":
        score += 0.35
        evidence.append("PER/PBRは過度な割高感を示していません。")
    elif valuation.get("direction") == "expensive":
        score -= 0.35
        risks.append("PER/PBR面では割高感があります。")

    if profitability.get("direction") == "strong":
        score += 0.45
        evidence.append("ROE水準から収益性が支援材料です。")
    elif profitability.get("direction") == "weak":
        score -= 0.45
        risks.append("ROE水準が低く、収益性面の支援は弱いです。")

    if safety.get("direction") == "strong":
        score += 0.25
        evidence.append("自己資本比率から財務安全性があります。")
    elif safety.get("direction") == "weak":
        score -= 0.3
        risks.append("自己資本比率が低く、財務リスクに注意が必要です。")

    if returns.get("direction") == "supportive":
        score += 0.25
        evidence.append("配当利回りは株主還元面の支援材料です。")
    elif returns.get("direction") == "limited":
        score -= 0.1
        risks.append("株主還元面の支援は限定的です。")
    return score


def _disclosure_score(disclosures: list[dict[str, Any]]) -> tuple[float, list[str], list[str]]:
    score = 0.0
    evidence: list[str] = []
    risks: list[str] = []
    for item in disclosures[:6]:
        text = f"{item.get('title') or ''} {item.get('summary') or ''}"
        item_score = _keyword_score(text)
        category = _classify(text)
        if category == "forecast_revision":
            evidence.append(f"業績予想修正に関連する開示: {item.get('title')}")
        elif item.get("title"):
            evidence.append(f"決算・財務関連開示: {item.get('title')}")
        if item_score < -0.2 and item.get("title"):
            risks.append(f"悪材料候補の開示: {item.get('title')}")
        score += item_score * 0.45
    return _clamp(score, -1.4, 1.4), evidence, risks


def _metric_evidence(snapshot: dict[str, Any]) -> list[str]:
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    if not isinstance(metrics, dict):
        return []
    evidence = []
    for key in ["per", "pbr", "roe", "equity_ratio", "dividend_yield", "eps", "bps"]:
        metric = metrics.get(key)
        if not isinstance(metric, dict):
            continue
        name = metric.get("name") or key.upper()
        value = metric.get("value")
        suffix = metric.get("suffix") or ""
        if value is not None:
            evidence.append(f"{name}は{value}{suffix}です。")
    return evidence[:6]


def _keyword_score(text: str) -> float:
    score = 0.0
    for term, value in POSITIVE_TERMS.items():
        if term in text:
            score += value * 0.12
    for term, value in NEGATIVE_TERMS.items():
        if term in text:
            score += value * 0.12
    return _clamp(score, -0.3, 0.3)


def _keyword_evidence(text: str) -> list[str]:
    hits = [term for term in [*POSITIVE_TERMS.keys(), *NEGATIVE_TERMS.keys()] if term in text]
    return [f"材料語句「{term}」を含みます。" for term in hits[:4]]


def _news_evidence(title: str, summary: str) -> list[str]:
    evidence = []
    if title:
        evidence.append(f"タイトル: {title}")
    for label in ["分類", "要約", "要点", "注意", "材料性", "根拠"]:
        value = _summary_field(summary, label)
        if value:
            evidence.append(f"{label}: {value}")
    if summary and len(evidence) <= 1:
        evidence.append(f"保存要約: {summary}")
    return evidence[:7]


def _classify(text: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "other"


def _topic_category(topic: str | None) -> str | None:
    mapping = {
        "決算・業績": "earnings",
        "株主還元": "dividend",
        "事業・受注": "business_alliance",
        "規制・政策": "regulation",
        "マクロ経済": "macro",
        "地政学": "macro",
        "市況・需給": "industry",
        "アナリスト": "analyst",
    }
    return mapping.get(topic or "")


def _assessment_score(assessment: dict[str, Any]) -> float:
    score = _num(assessment.get("direction_score"))
    if score is None:
        return 0.0
    return _clamp(score, -1.0, 1.0)


def _impact_score(item: dict[str, Any], category: str, direction_score: float, assessment: dict[str, Any] | None = None) -> float:
    source_type = item.get("type")
    if assessment:
        assessed_impact = _num(assessment.get("impact_score"))
        assessed_relevance = _num(assessment.get("company_relevance"))
        if assessed_impact is not None:
            if assessed_relevance is not None and assessed_relevance < 0.25:
                assessed_impact *= 0.5
            return _clamp(assessed_impact, 0.0, 1.0)
    if source_type == "disclosure":
        base = 0.72
    elif source_type == "global_news":
        base = 0.42
    else:
        base = 0.5
    if category in {"forecast_revision", "earnings", "dividend", "share_buyback"}:
        base += 0.18
    if abs(direction_score) >= 1.0:
        base += 0.08
    importance = _num(item.get("importance_score"))
    relevance = _num(item.get("relevance_score"))
    if importance is not None:
        base = max(base, min(1.0, importance))
    if relevance is not None:
        base *= max(0.5, min(1.0, relevance))
    return _clamp(base, 0.0, 1.0)


def _material_summary(score: float, title: str, summary: str, llm_topic: str | None, assessment: dict[str, Any] | None = None) -> str:
    direction = "ポジティブ" if score >= 0.35 else "ネガティブ" if score <= -0.35 else "中立"
    summary_text = _summary_field(summary, "要約") or _plain_summary(summary)
    materiality = _summary_field(summary, "材料性")
    topic_text = f"LLM分類: {llm_topic}。 " if llm_topic else ""
    materiality_text = f"材料性: {materiality}。 " if materiality else ""
    assessment_text = f"材料評価: {assessment.get('reason')} " if assessment and assessment.get("reason") else ""
    if summary_text:
        return f"{topic_text}{materiality_text}{assessment_text}記事要約: {summary_text} 中長期方向は{direction}寄りです。タイトル: {title}"
    return f"{topic_text}{materiality_text}{assessment_text}記事本文の要約は未取得です。中長期方向は{direction}寄りです。タイトル: {title}"


def _material_risks(category: str, score: float, item: dict[str, Any], summary: str, assessment: dict[str, Any] | None = None) -> list[str]:
    risks = []
    for risk in (assessment or {}).get("risk_notes") or []:
        risks.append(str(risk))
    if assessment and assessment.get("expectation_gap") == "unknown":
        risks.append("市場期待とのギャップは入力にないため断定しません。")
    summary_risk = _summary_field(summary, "注意")
    if summary_risk:
        risks.append(f"要約上の注意: {summary_risk}")
    age_days = item.get("age_days")
    if isinstance(age_days, int) and age_days > 30:
        risks.append("30日超の材料で、価格への即時影響は減衰している可能性があります。")
    if category in {"forecast_revision", "earnings"} and score > 0:
        risks.append("決算・業績材料は発表後の材料出尽くしに注意が必要です。")
    if category in {"macro", "industry", "regulation"}:
        risks.append("外部要因は銘柄業績への影響度が不確実です。")
    return risks or ["ニュース本文の詳細未取得部分は断定しません。"]


def _summary_field(summary: str, label: str) -> str | None:
    if not summary:
        return None
    labels = "分類|要約|要点|注意|材料性|根拠"
    pattern = rf"(?:^|\s){re.escape(label)}[:：]\s*(.*?)(?=\s(?:{labels})[:：]|$)"
    match = re.search(pattern, summary)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip()
    return value or None


def _plain_summary(summary: str) -> str | None:
    if not summary:
        return None
    if re.search(r"(?:^|\s)(分類|要約|要点|注意|材料性|根拠)[:：]", summary):
        return None
    text = re.sub(r"\s+", " ", summary).strip()
    if not text:
        return None
    return text[:260] + ("..." if len(text) > 260 else "")


def _technical_summary(score: float, evidence: list[str], risks: list[str]) -> str:
    if score >= 0.7:
        return "テクニカルは中長期判断の確認材料として強気寄りです。" + (" " + evidence[0] if evidence else "")
    if score <= -0.7:
        return "テクニカルは中長期判断の確認材料として弱気寄りです。" + (" " + evidence[0] if evidence else "")
    if risks:
        return "テクニカルは中立からやや慎重です。" + " " + risks[0]
    return "テクニカルは中立です。"


def _fundamental_summary(score: float, evidence: list[str], risks: list[str]) -> str:
    if score >= 0.7:
        return "ファンダメンタルは中長期判断の支援材料です。" + (" " + evidence[0] if evidence else "")
    if score <= -0.7:
        return "ファンダメンタルは中長期判断のリスク材料です。" + (" " + risks[0] if risks else "")
    if evidence:
        return "ファンダメンタルは中立からやや支援的です。" + " " + evidence[0]
    return "ファンダメンタルの方向感は限定的です。"


def _weighted_average(cards: list[dict[str, Any]]) -> float:
    if not cards:
        return 0.0
    weights = [
        max(0.05, float(card.get("impact_score") or 0) * float(card.get("confidence") or 0) * float(card.get("freshness_score") or 0))
        for card in cards
    ]
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(float(card.get("direction_score") or 0) * weight for card, weight in zip(cards, weights)) / total


def _top_cards(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(
        cards,
        key=lambda card: (
            float(card.get("impact_score") or 0)
            * float(card.get("confidence") or 0)
            * max(0.2, float(card.get("freshness_score") or 0))
        ),
        reverse=True,
    )[:limit]


def _joined_summary(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "該当するSignal Cardはありません。"
    return " / ".join(card.get("summary") or "" for card in cards[:3] if card.get("summary"))


def _conflict_level(scores: list[float]) -> str:
    positives = [score for score in scores if score >= 0.5]
    negatives = [score for score in scores if score <= -0.5]
    if positives and negatives:
        if max(positives) - min(negatives) >= 1.6:
            return "high"
        return "medium"
    return "low"


def _bias(score: float) -> str:
    if score >= 0.45:
        return "bullish"
    if score <= -0.45:
        return "bearish"
    return "neutral"


def _freshness(age_days: Any) -> float:
    age = _num(age_days)
    if age is None:
        return 0.55
    if age <= 1:
        return 1.0
    if age <= 7:
        return 0.86
    if age <= 30:
        return 0.62
    if age <= 90:
        return 0.36
    return 0.2


def _days_old(iso_date: Any, base_date: Any) -> int | None:
    if not iso_date or not base_date:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_date)[:10]).date()
        base = datetime.fromisoformat(str(base_date)[:10]).date()
    except ValueError:
        return None
    return (base - parsed).days


def _packet_rows(packet: dict[str, Any]) -> list[list[Any]]:
    company = packet.get("company") or {}
    data_status = packet.get("data_status") or {}
    return [
        ["銘柄コード", company.get("security_code")],
        ["会社名", company.get("name")],
        ["市場", company.get("market")],
        ["業種", company.get("industry")],
        ["主力/関連テーマ", ", ".join((packet.get("company_profile") or {}).get("business_terms") or [])],
        ["判断基準日", packet.get("as_of")],
        ["価格データ基準日", data_status.get("price_data_as_of")],
        ["欠損/警告", ", ".join(data_status.get("missing_data") or []) or "なし"],
    ]


def _company_profile_rows(profile: dict[str, Any]) -> list[list[Any]]:
    return [
        ["会社名・表記", profile.get("company_terms")],
        ["主力/関連テーマ", profile.get("business_terms")],
        ["重視材料語", profile.get("material_terms")],
        ["除外語", profile.get("exclude_terms")],
        ["業種", profile.get("industry")],
        ["決算/会社概要", profile.get("financial_summary")],
        ["解釈ルール", profile.get("interpretation_rule")],
        ["profile_source", profile.get("profile_source")],
    ]


def _summary_table(summary: dict[str, Any]) -> str:
    return _table(
        ["項目", "値"],
        [
            ["direction_score", summary.get("direction_score")],
            ["impact_score", summary.get("impact_score")],
            ["summary", summary.get("summary")],
            ["risk_notes", " / ".join(summary.get("risk_notes") or [])],
        ],
    )


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [["なし" for _ in headers]]
    normalized_rows = [[_cell(value) for value in row] for row in rows]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(row[: len(headers)] + [""] * max(0, len(headers) - len(row))) + " |" for row in normalized_rows],
        ]
    )


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = ", ".join(f"{key}: {item}" for key, item in value.items())
    else:
        text = str(value)
    return text.replace("\n", " ").replace("|", "/")


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
