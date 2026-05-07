# LLMパイプライン設計書

## 1. 目的

本設計書は、日本株短期売買判断支援ソフトウェアにおける **LLM入力・判断パイプライン** を定義する。

本ソフトウェアでは、ニュース、決算・ファンダメンタル情報、株価・テクニカル情報を統合し、ローカルLLMによって短期売買判断を行う。

ただし、ローカルLLMに生データを直接渡すのではなく、各データソースを段階的に処理し、最終的にLLMが扱いやすい構造化入力へ変換する。

---

## 2. 基本方針

### 2.1 LLMに直接渡さないもの

以下の情報は、原則としてLLMにそのまま渡さない。

- 株価の全時系列データ
- ニュース記事全文
- 決算短信全文
- 有価証券報告書全文
- PDF全文
- 未加工のHTML
- 大量の未整理テキスト
- 未計算の数値データ

---

### 2.2 LLMに渡すもの

LLMには、以下のように整理・圧縮された情報を渡す。

- テクニカル特徴量
- ニュースの要約と材料性判定
- 決算・ファンダメンタル情報の主要指標
- データ鮮度
- リスク情報
- 情報源ごとの強弱シグナル
- 統合済みの Context Packet

---

### 2.3 役割分担

| 処理 | 担当 |
|---|---|
| データ取得 | Python |
| 欠損チェック | Python |
| 数値計算 | Python |
| テクニカル指標計算 | Python |
| ニュースの要約 | LLM |
| ニュースの材料性判定 | LLM |
| 決算コメントの要約 | LLM |
| 最終判断 | LLM |
| JSON検証 | Python |
| 判断保存 | Python / SQLite |
| 後日検証 | Python |

LLMには「計算」ではなく「解釈」と「統合判断」を担当させる。

---

## 3. 全体パイプライン

```text
[Phase 0] 対象銘柄・更新範囲の決定
    ↓
[Phase 1] データ取得
    ├─ ニュース
    ├─ 決算・開示・ファンダメンタル
    └─ 株価・出来高
    ↓
[Phase 2] 正規化・銘柄紐付け
    ├─ 証券コードへ紐付け
    ├─ 重複排除
    ├─ 日付・ソース統一
    └─ 信頼度付与
    ↓
[Phase 3] Source別解析
    ├─ Technical Analyzer
    ├─ News Analyzer
    └─ Fundamental Analyzer
    ↓
[Phase 4] Signal Card生成
    ↓
[Phase 5] 銘柄別 Context Packet作成
    ↓
[Phase 6] LLM最終判断
    ↓
[Phase 7] 出力検証・DB保存・後日検証
```

---

## 4. 中間形式: Signal Card

### 4.1 Signal Cardの役割

Signal Cardは、ニュース、ファンダメンタル、テクニカルなど異なる種類の情報を、共通形式で扱うための中間表現である。

各情報源は、最終的に1つ以上のSignal Cardへ変換される。

```text
ニュース記事        → News Signal Card
決算情報            → Fundamental Signal Card
株価・出来高        → Technical Signal Card
市場・マクロ情報    → Market Signal Card
```

---

### 4.2 Signal Card共通スキーマ

```json
{
  "signal_id": "sig_20260428_7203_001",
  "company_code": "7203",
  "source_type": "news",
  "source_name": "company_ir",
  "published_at": "2026-04-28",
  "horizon": "short_term",
  "direction": "bullish",
  "direction_score": 1.0,
  "impact_score": 0.7,
  "confidence": 0.8,
  "freshness_score": 0.95,
  "relevance_score": 0.9,
  "summary": "会社が通期業績予想を上方修正した。短期的には買い材料になりやすい。",
  "evidence": [
    "通期営業利益予想を前回予想から上方修正",
    "売上高予想も同時に引き上げ"
  ],
  "risk_notes": [
    "すでに株価が反応済みの可能性がある"
  ]
}
```

---

### 4.3 Signal Cardの項目定義

| 項目 | 型 | 説明 |
|---|---|---|
| `signal_id` | string | Signal Cardの一意ID |
| `company_code` | string | 証券コード |
| `source_type` | string | `technical`, `news`, `fundamental`, `market` など |
| `source_name` | string | データ取得元 |
| `published_at` | string | 情報の公開日時 |
| `horizon` | string | `short_term`, `mid_long_term` など |
| `direction` | string | `bullish`, `bearish`, `neutral`, `unknown` |
| `direction_score` | number | -2.0〜+2.0程度の方向スコア |
| `impact_score` | number | 0〜1の影響度 |
| `confidence` | number | 0〜1の判定信頼度 |
| `freshness_score` | number | 0〜1の鮮度 |
| `relevance_score` | number | 0〜1の銘柄関連度 |
| `summary` | string | 短い要約 |
| `evidence` | array | 判断根拠 |
| `risk_notes` | array | 注意点 |

---

## 5. Technical Pipeline

### 5.1 目的

Technical Pipelineでは、株価・出来高データから短期売買判断に必要なテクニカル特徴量を生成する。

テクニカル情報は数値処理が中心であるため、原則としてLLMを使用しない。

---

### 5.2 処理フロー

```text
株価OHLCV
  ↓
欠損チェック
  ↓
移動平均計算
  ↓
騰落率計算
  ↓
出来高倍率計算
  ↓
ボラティリティ計算
  ↓
高値・安値更新判定
  ↓
ギャップ判定
  ↓
トレンド判定
  ↓
Technical Signal Card生成
```

---

### 5.3 計算する特徴量

```json
{
  "last_close": 1520,
  "change_1d_pct": 1.8,
  "change_5d_pct": 4.5,
  "change_20d_pct": 9.2,
  "ma_5": 1490,
  "ma_25": 1420,
  "ma_75": 1360,
  "price_vs_ma_5_pct": 2.0,
  "price_vs_ma_25_pct": 7.0,
  "price_vs_ma_75_pct": 11.7,
  "volume_ratio_5d": 1.8,
  "volatility_20d": 0.026,
  "trend_short": "up",
  "trend_middle": "up",
  "recent_high_break": true,
  "recent_low_break": false,
  "gap_up": false,
  "gap_down": false,
  "overheated": true
}
```

---

### 5.4 Technical Signal Card例

```json
{
  "source_type": "technical",
  "horizon": "short_term",
  "direction": "bullish",
  "direction_score": 1.2,
  "impact_score": 0.65,
  "confidence": 0.75,
  "freshness_score": 1.0,
  "relevance_score": 1.0,
  "summary": "株価は5日・25日・75日移動平均線を上回り、短期上昇トレンドにある。出来高も増加している。",
  "evidence": [
    "終値が5日MAを2.0%上回る",
    "終値が25日MAを7.0%上回る",
    "出来高が5日平均比1.8倍",
    "20日高値を更新"
  ],
  "risk_notes": [
    "20日騰落率が高く、短期過熱感がある"
  ]
}
```

---

## 6. News Pipeline

### 6.1 目的

News Pipelineでは、企業ニュース、適時開示、業界ニュース、マクロニュースを処理し、短期株価への影響をSignal Cardとして表現する。

ニュースはノイズが多いため、1記事ごとに処理し、重要なものだけを最終判断へ渡す。

---

### 6.2 処理フロー

```text
ニュース取得
  ↓
重複排除
  ↓
銘柄紐付け
  ↓
本文抽出・短縮
  ↓
ニュース分類
  ↓
材料性判定
  ↓
News Signal Card生成
```

---

### 6.3 ニュース分類

ニュースは以下のカテゴリへ分類する。

```text
earnings
forecast_revision
dividend
share_buyback
new_product
business_alliance
ma
lawsuit
scandal
regulation
macro
industry
analyst
market_commentary
other
```

---

### 6.4 ニュース用LLM入力

```json
{
  "company": {
    "security_code": "7203",
    "name": "トヨタ自動車",
    "industry": "輸送用機器"
  },
  "article": {
    "title": "トヨタ、通期営業利益予想を上方修正",
    "published_at": "2026-04-28",
    "source": "company_ir",
    "text_excerpt": "同社は通期営業利益予想を前回予想から引き上げた..."
  },
  "task": "この記事が対象銘柄の短期株価に与える影響を判定してください。"
}
```

---

### 6.5 ニュース解析LLMの出力

```json
{
  "category": "forecast_revision",
  "direction": "bullish",
  "direction_score": 1.4,
  "impact_score": 0.85,
  "confidence": 0.82,
  "relevance_score": 0.95,
  "summary": "通期業績予想の上方修正は、短期的にポジティブ材料になりやすい。",
  "evidence": [
    "会社が通期営業利益予想を上方修正",
    "売上高予想も引き上げ"
  ],
  "risk_notes": [
    "発表前に株価が上昇していた場合は材料出尽くしに注意"
  ]
}
```

---

### 6.6 News Signal Card例

```json
{
  "source_type": "news",
  "source_name": "company_ir",
  "horizon": "short_term",
  "direction": "bullish",
  "direction_score": 1.4,
  "impact_score": 0.85,
  "confidence": 0.82,
  "freshness_score": 1.0,
  "relevance_score": 0.95,
  "summary": "通期業績予想の上方修正は、短期的にポジティブ材料になりやすい。",
  "evidence": [
    "会社が通期営業利益予想を上方修正",
    "売上高予想も引き上げ"
  ],
  "risk_notes": [
    "発表前に株価が上昇していた場合は材料出尽くしに注意"
  ]
}
```

---

## 7. Fundamental Pipeline

### 7.1 目的

Fundamental Pipelineでは、決算情報、業績予想、配当、財務指標などを処理する。

MVPの短期判断では、ファンダメンタル情報は企業価値評価ではなく、短期イベント・材料として扱う。

---

### 7.2 処理フロー

```text
決算情報取得
  ↓
主要数値抽出
  ↓
前年比・進捗率計算
  ↓
会社予想修正の有無判定
  ↓
配当修正の有無判定
  ↓
決算インパクト判定
  ↓
Fundamental Signal Card生成
```

---

### 7.3 主要特徴量

```json
{
  "revenue_yoy_pct": 8.2,
  "operating_profit_yoy_pct": 15.5,
  "ordinary_profit_yoy_pct": 13.0,
  "net_income_yoy_pct": 10.1,
  "operating_margin": 0.12,
  "forecast_revision": "upward",
  "dividend_revision": "unchanged",
  "earnings_progress_rate": 0.58,
  "days_since_earnings": 3,
  "days_to_next_earnings": 87
}
```

---

### 7.4 Fundamental Signal Card例

```json
{
  "source_type": "fundamental",
  "horizon": "short_term",
  "direction": "bullish",
  "direction_score": 1.1,
  "impact_score": 0.75,
  "confidence": 0.78,
  "freshness_score": 0.9,
  "relevance_score": 1.0,
  "summary": "直近決算は増収増益で、会社予想も上方修正されている。短期的にはポジティブ材料。",
  "evidence": [
    "営業利益が前年同期比15.5%増",
    "通期予想を上方修正",
    "決算発表から3営業日以内"
  ],
  "risk_notes": [
    "短期的には決算反応後の利確売りに注意"
  ]
}
```

---

## 8. Signal統合パイプライン

### 8.1 目的

Signal統合パイプラインでは、Technical、News、FundamentalのSignal Cardを銘柄ごとに集約し、最終LLM判断用のContext Packetを作成する。

---

### 8.2 処理フロー

```text
Technical Signal Cards
News Signal Cards
Fundamental Signal Cards
Market Signal Cards
  ↓
重要度順に並べ替え
  ↓
古い情報を減衰
  ↓
矛盾を検出
  ↓
重み付きスコアを計算
  ↓
Context Packet作成
```

---

### 8.3 短期判断の基本重み

通常時は以下の重みを使う。

| 情報 | 重み |
|---|---:|
| テクニカル | 0.50 |
| ニュース | 0.30 |
| ファンダメンタル | 0.20 |

---

### 8.4 イベント時の重み

決算直後は以下の重みに変更する。

| 情報 | 重み |
|---|---:|
| テクニカル | 0.35 |
| ニュース・開示 | 0.35 |
| ファンダメンタル | 0.30 |

材料がない場合は以下の重みに変更する。

| 情報 | 重み |
|---|---:|
| テクニカル | 0.70 |
| ニュース | 0.15 |
| ファンダメンタル | 0.15 |

---

### 8.5 Aggregated Signal計算

基本式は以下。

```text
weighted_score =
  technical_score * technical_weight
+ news_score * news_weight
+ fundamental_score * fundamental_weight
```

ただし、最終判断はスコアだけで決めない。

LLMには以下も渡す。

- 重要Signal
- リスク要因
- データ鮮度
- データ欠損
- 情報源間の矛盾
- イベント発生状況

---

## 9. Context Packet

### 9.1 Context Packetの役割

Context Packetは、最終判断LLMに渡すための統合入力である。

ローカルLLMの文脈長と安定性を考慮し、情報は要約済み・構造化済みのものに限定する。

---

### 9.2 Context Packet例

```json
{
  "company": {
    "security_code": "7203",
    "name": "トヨタ自動車",
    "market": "Prime",
    "industry": "輸送用機器"
  },
  "as_of": "2026-04-28",
  "judgement_type": "short_term",
  "time_horizon": "several_days_to_3_weeks",
  "data_status": {
    "price_data_as_of": "2026-04-26",
    "news_checked_until": "2026-04-28T10:00:00",
    "fundamental_data_as_of": "2026-04-25",
    "has_stale_data": false,
    "missing_data": []
  },
  "technical_summary": {
    "direction_score": 1.2,
    "impact_score": 0.65,
    "summary": "短期上昇トレンド。5日・25日・75日MAを上回り、出来高も増加。",
    "risk_notes": [
      "20日騰落率が高く、短期過熱感がある"
    ]
  },
  "news_summary": {
    "direction_score": 0.8,
    "impact_score": 0.6,
    "summary": "直近ニュースはややポジティブ。業績上方修正に関する開示がある。",
    "top_signals": [
      {
        "summary": "通期営業利益予想を上方修正",
        "direction": "bullish",
        "impact_score": 0.85,
        "published_at": "2026-04-28"
      }
    ]
  },
  "fundamental_summary": {
    "direction_score": 1.1,
    "impact_score": 0.75,
    "summary": "直近決算は増収増益。会社予想も上方修正。",
    "risk_notes": [
      "決算発表直後のため材料出尽くしに注意"
    ]
  },
  "aggregated_signal": {
    "technical_score": 1.2,
    "news_score": 0.8,
    "fundamental_score": 1.1,
    "weighted_score": 1.05,
    "conflict_level": "low",
    "overall_bias": "bullish"
  }
}
```

---

## 10. Final Judgement Pipeline

### 10.1 目的

Final Judgement Pipelineでは、Context Packetを入力として、ローカルLLMに最終的な短期売買判断を行わせる。

---

### 10.2 最終判断LLM入力

```json
{
  "task": "日本株の短期売買判断を行ってください。",
  "rules": {
    "allowed_actions": [
      "BUY",
      "WATCH_BUY",
      "NO_TRADE",
      "WATCH_SELL",
      "SELL",
      "INSUFFICIENT_DATA"
    ],
    "time_horizon": "several_days_to_3_weeks",
    "must_consider": [
      "technical_summary",
      "news_summary",
      "fundamental_summary",
      "data_status",
      "aggregated_signal"
    ],
    "do_not": [
      "入力にない事実を作らない",
      "長期投資判断をしない",
      "リアルタイム株価がある前提で判断しない"
    ]
  },
  "context_packet": {}
}
```

---

### 10.3 最終判断LLM出力

```json
{
  "judgement_type": "short_term",
  "action": "WATCH_BUY",
  "confidence": 0.69,
  "time_horizon": "several_days_to_3_weeks",
  "summary": "テクニカル、ニュース、決算情報はいずれも短期的にポジティブだが、直近上昇と決算後の材料出尽くしリスクがあるため、即時BUYではなくWATCH_BUYが妥当。",
  "positive_factors": [
    "株価が主要移動平均線を上回っている",
    "出来高が増加している",
    "業績予想の上方修正が確認されている"
  ],
  "negative_factors": [
    "短期上昇率が高く過熱感がある",
    "決算発表後の利確売りが出る可能性がある"
  ],
  "entry_conditions": [
    "25日移動平均線を割らずに反発する",
    "出来高を伴って直近高値を再更新する",
    "決算後の下落が限定的である"
  ],
  "exit_conditions": [
    "終値で25日移動平均線を明確に下回る",
    "出来高を伴う大陰線が出る",
    "業績見通しに悪材料が出る"
  ],
  "risk_notes": [
    "日次データベースの判断であり、リアルタイム性はない",
    "短期的には材料出尽くしに注意"
  ],
  "used_signal_types": [
    "technical",
    "news",
    "fundamental"
  ]
}
```

---

## 11. SQLite追加テーブル

### 11.1 news_items

```sql
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    title TEXT NOT NULL,
    source TEXT,
    url TEXT,
    published_at TEXT,
    body_text_path TEXT,
    summary TEXT,
    category TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);
```

---

### 11.2 fundamental_snapshots

```sql
CREATE TABLE fundamental_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    fiscal_period TEXT,
    disclosed_at TEXT,

    revenue REAL,
    operating_profit REAL,
    ordinary_profit REAL,
    net_income REAL,
    eps REAL,
    dividend REAL,

    revenue_yoy_pct REAL,
    operating_profit_yoy_pct REAL,
    net_income_yoy_pct REAL,
    forecast_revision TEXT,
    dividend_revision TEXT,

    source TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);
```

---

### 11.3 signal_cards

```sql
CREATE TABLE signal_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,

    source_type TEXT NOT NULL,
    source_id INTEGER,
    source_name TEXT,

    horizon TEXT NOT NULL,
    direction TEXT NOT NULL,
    direction_score REAL NOT NULL,
    impact_score REAL NOT NULL,
    confidence REAL NOT NULL,
    freshness_score REAL,
    relevance_score REAL,

    summary TEXT NOT NULL,
    evidence_json TEXT,
    risk_notes_json TEXT,

    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX idx_signal_cards_company_horizon_created
ON signal_cards(company_id, horizon, created_at);
```

---

## 12. 実装フェーズ

### Phase 1: Technical Only

最初はテクニカル情報だけでLLM判断を行う。

```text
株価データ
  ↓
テクニカル特徴量
  ↓
Technical Signal Card
  ↓
Context Packet
  ↓
LLM短期判断
```

目的は、Signal Card方式とLLM最終判断の最小構成を確認すること。

---

### Phase 2: News追加

```text
ニュース
  ↓
銘柄紐付け
  ↓
記事単位の材料判定
  ↓
News Signal Card
  ↓
Context Packetへ追加
```

目的は、テクニカル判断に材料情報を加えること。

---

### Phase 3: Fundamental追加

```text
決算情報
  ↓
主要数値抽出
  ↓
前年比・修正有無計算
  ↓
Fundamental Signal Card
  ↓
Context Packetへ追加
```

目的は、短期判断に決算イベント・業績修正情報を加えること。

---

### Phase 4: 統合判断

```text
Technical Signal
News Signal
Fundamental Signal
  ↓
Aggregated Signal
  ↓
Final LLM Judgement
  ↓
判断履歴保存
```

目的は、各情報源の矛盾や重みを考慮した最終判断を行うこと。

---

### Phase 5: 検証・改善

```text
AI判断
  ↓
5営業日後・20営業日後の株価確認
  ↓
判断精度を記録
  ↓
プロンプト・重み・Signal化ルールを改善
```

目的は、LLM判断が有効に機能しているかを継続的に検証すること。

---

## 13. エラーハンドリング

### 13.1 データ不足

以下の場合、最終判断では `INSUFFICIENT_DATA` を優先する。

- 株価データが不足している
- 最新データが古い
- 移動平均が計算できない
- ニュース取得に失敗している
- 決算データの更新状態が不明
- Signal Cardが生成できていない

---

### 13.2 LLM出力不正

LLM出力がJSON Schemaに違反した場合は、以下を行う。

```text
1. 1回だけ再実行する
2. 再実行でも失敗した場合は judgement_failed として記録する
3. ai_judgementsには保存しない、または failed statusで保存する
4. data_update_logsに失敗理由を保存する
```

---

### 13.3 矛盾が大きい場合

以下のような場合は、最終判断で `NO_TRADE` または `INSUFFICIENT_DATA` を優先する。

- テクニカルは強気だが、重大な悪材料ニュースがある
- 決算は良いが、株価が高値圏で急落している
- ニュースが強気だが、出来高が伴っていない
- ファンダメンタルが弱く、短期上昇だけが先行している

---

## 14. 最終判断プロンプト方針

最終判断プロンプトでは、以下を明示する。

```text
あなたは日本株の短期売買判断エンジンです。
入力されたContext Packetのみを根拠として、数日〜3週間程度の短期判断を行ってください。

以下を必ず考慮してください。
- テクニカル情報
- ニュース情報
- ファンダメンタル情報
- データ鮮度
- 情報源間の矛盾
- 短期過熱感
- 決算直前・直後リスク

以下は禁止です。
- 入力にない事実を作ること
- 長期投資判断を行うこと
- リアルタイム株価がある前提で判断すること
- 根拠が弱いのにBUYまたはSELLを出すこと

判断材料が弱い場合は、NO_TRADEまたはINSUFFICIENT_DATAを選んでください。
```

---

## 15. MVPでの推奨実装順

MVPでは以下の順に実装する。

```text
1. Technical Signal Card生成
2. TechnicalのみのContext Packet生成
3. ローカルLLMによる短期判断
4. 判断履歴保存
5. 判断後リターン検証
6. News Signal Card追加
7. Fundamental Signal Card追加
8. Signal統合スコア追加
9. 矛盾検出追加
10. プロンプト改善
```

---

## 16. この設計の要点

本パイプラインの要点は以下である。

```text
- LLMに生データを渡さない
- 情報源ごとに解析パイプラインを分ける
- 各情報をSignal Cardに変換する
- 最終判断LLMにはContext Packetだけを渡す
- テクニカル計算はPythonで行う
- ニュース・決算の解釈はLLMを使う
- 最終判断は構造化JSONで保存する
- 判断後の株価推移を検証し、継続的に改善する
```

---
