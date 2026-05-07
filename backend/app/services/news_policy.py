from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Literal


NewsAction = Literal["ignore", "title_only", "summarize"]


@dataclass(frozen=True)
class NewsDecision:
    action: NewsAction
    reason: str


HIGH_VALUE_PATTERNS = [
    r"決算",
    r"業績予想",
    r"上方修正|下方修正",
    r"増配|減配|配当",
    r"自社株|自己株式",
    r"TOB|M&A|買収|売却|資本提携|業務提携",
    r"大型受注|受注|契約|認可|承認",
    r"行政処分|不正|訴訟|調査",
    r"新工場|生産能力|設備投資|撤退|閉鎖",
    r"関税|制裁|輸出規制|規制",
    r"地政学|戦争|紛争|中東|紅海|台湾|中国|米国|欧州|ロシア|ウクライナ",
    r"日銀|金融政策|金利|為替|円安|円高|ドル",
    r"原油|LNG|ナフサ|資源|サプライチェーン",
    r"半導体|生成AI|AI|データセンター|EV|電池",
]

LOW_VALUE_PATTERNS = [
    r"本日の【.*】",
    r"明日の好悪材料",
    r"好悪材料",
    r"決算発表予定",
    r"前日に動いた株",
    r"話題株ピックアップ",
    r"注目銘柄ダイジェスト",
    r"寄前【成行注文】",
    r"後場に注目すべき",
    r"大引け|前引け",
    r"ランキング",
    r"アクセスランキング",
    r"出来高変化率ランキング",
    r"レーティング日報",
    r"信用残ランキング",
    r"高配当利回り",
    r"低PBR",
    r"低PER",
    r"株価指数先物",
    r"ADR日本株",
]

LOW_VALUE_PROVIDERS = {"株探", "みんかぶ", "フィスコ"}
SUMMARY_PROVIDERS = {"ロイター", "Reuters", "Bloomberg", "日本経済新聞", "日経", "NHK", "共同通信", "時事通信"}


def decide_company_news(title: str | None, provider: str | None) -> NewsDecision:
    clean_title = _clean(title)
    clean_provider = _clean(provider)
    if not clean_title:
        return NewsDecision("ignore", "empty_title")
    if _matches(clean_title, LOW_VALUE_PATTERNS):
        return NewsDecision("ignore", "low_value_recurring_column")
    if _matches(clean_title, HIGH_VALUE_PATTERNS):
        return NewsDecision("summarize", "high_value_keyword")
    if _provider_contains(clean_provider, SUMMARY_PROVIDERS):
        return NewsDecision("summarize", "trusted_provider")
    if _provider_contains(clean_provider, LOW_VALUE_PROVIDERS):
        return NewsDecision("title_only", "low_signal_provider")
    return NewsDecision("title_only", "unclassified")


def canonical_news_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _provider_contains(provider: str, names: set[str]) -> bool:
    return any(name.lower() in provider.lower() for name in names)


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
