# 日本株短期売買判断支援ソフトウェア 設計書 v0.1

## 1. 概要

本ソフトウェアは、日本株の短期売買判断を支援する個人用ソフトウェアである。

株価データ、テクニカル指標、出来高、直近の適時開示・決算関連情報を統合し、ローカルLLMによって短期売買判断を生成する。

初期バージョンでは、リアルタイム株価、自動売買、証券口座連携、有料データAPIの利用は対象外とする。

---

## 2. 目的

本ソフトウェアの目的は、以下である。

- 日本株の短期売買判断を効率化する
- ウォッチ銘柄の株価・出来高・テクニカル状態を一覧で把握する
- 直近の開示情報やイベントを考慮して売買判断を補助する
- ローカルLLMにより、BUY / SELL などの最終判断を構造化して出力する
- LLMの判断履歴を保存し、後から検証可能にする

---

## 3. 想定利用者

本ソフトウェアは、開発者本人が利用する個人用ツールとする。

一般公開、SaaS提供、法人利用、投資助言サービスとしての提供は、初期スコープに含めない。

---

## 4. 基本方針

### 4.1 プロダクト方針

本ソフトウェアは、以下の方針で設計する。

- 日本株に特化する
- 初期判断対象は短期売買とする
- データは日次更新を基本とする
- リアルタイム性は求めない
- LLMには最終判断まで行わせる
- ただし、LLMには株価計算をさせない
- Python側で特徴量を計算し、LLMには判断を担当させる
- ローカルLLMを基本とし、外部LLM APIは初期段階では利用しない
- データ保存はSQLiteを用いる
- 初期UIはWebアプリとし、将来的にPWAまたはデスクトップアプリ化を検討する

---

## 5. MVPスコープ

### 5.1 MVPで実装する機能

MVPでは以下を実装対象とする。

- 日本株銘柄検索
- ウォッチリスト管理
- 日足チャート表示
- 週足・月足への切り替え
- ローソク足表示
- 移動平均線表示
  - 5日移動平均
  - 25日移動平均
  - 75日移動平均
- 出来高表示
- 日次株価データ保存
- テクニカル指標計算
- 直近適時開示・決算関連情報の取得または登録
- ローカルLLMによる短期売買判断
- AI判断履歴保存
- 判断根拠の保存
- データ更新ログ保存

---

### 5.2 MVPで実装しない機能

以下はMVPの対象外とする。

- リアルタイム株価取得
- 板情報取得
- 自動売買
- 証券会社API連携
- 注文発注
- ポートフォリオ最適化
- 中長期ファンダメンタル判断
- 高度なバックテスト
- 有料TDnet API連携
- 商用ニュースAPI連携
- スマホネイティブアプリ
- 一般公開SaaS化

---

## 6. システム構成

### 6.1 全体構成

```text
[Frontend: Web UI]
        |
        | HTTP
        v
[Backend: FastAPI]
        |
        |-------------------------
        |                         |
        v                         v
[SQLite Database]           [Ollama Local LLM]
        |
        v
[Local File Storage]
```

---

### 6.2 技術スタック

| 領域 | 採用技術 |
|---|---|
| フロントエンド | Next.js / React / TypeScript |
| バックエンド | Python / FastAPI |
| データベース | SQLite |
| チャート | TradingView Lightweight Charts 等 |
| LLM実行基盤 | Ollama |
| LLM呼び出し | OpenAI互換API または Ollama API |
| 文書保存 | ローカルファイル |
| バッチ処理 | Python scripts / APScheduler |
| アプリ化候補 | PWA / Tauri |

---

## 7. データソース設計

### 7.1 株価データ

株価データは、無料または低コストのデータソースを優先する。

候補は以下。

| 優先度 | データソース | 用途 |
|---|---|---|
| 高 | J-Quants Free | 日本株の日足・財務情報 |
| 中 | Stooq | 長期株価の補完 |
| 低 | Yahoo Finance / yfinance系 | 補助的利用 |

初期実装では、データソースを固定せず、`source` カラムで管理する。

---

### 7.2 適時開示・決算情報

適時開示情報は、MVPではウォッチ銘柄を中心に扱う。

初期方針は以下。

- 全銘柄の全開示取得は行わない
- ウォッチ銘柄の直近開示を優先する
- 必要に応じて手動登録も許容する
- PDF本文の完全解析はMVPでは必須としない
- タイトル、公開日、URL、要約を保存する

---

### 7.3 EDINET・有価証券報告書

MVPでは必須ではないが、将来拡張として考慮する。

初期段階では、短期判断に直接必要な情報ではないため、優先度は低い。

---

### 7.4 ニュース・マクロ情報

MVPでは、ニュース・マクロ情報の完全自動取得は対象外とする。

将来的には以下を検討する。

- 日経平均
- TOPIX
- 業種別指数
- 為替
- 金利
- 原油
- 日銀統計
- e-Stat
- 公的機関の公開情報
- RSS

---

## 8. 短期判断設計

### 8.1 判断対象期間

短期判断の対象期間は以下とする。

- 数日
- 1週間程度
- 最大3週間程度

---

### 8.2 判断単位

判断は銘柄ごと、対象日ごとに行う。

```text
1銘柄 × 1対象日 × 1判断種別
```

MVPでは判断種別は `short_term` のみとする。

---

### 8.3 判断アクション

LLMが出力するアクションは以下に限定する。

| アクション | 意味 |
|---|---|
| BUY | 短期買い候補 |
| WATCH_BUY | 買い監視 |
| NO_TRADE | 取引しない |
| WATCH_SELL | 売り警戒 |
| SELL | 売り候補 |
| INSUFFICIENT_DATA | 判断材料不足 |

---

### 8.4 短期判断に利用する情報

短期判断では、以下の情報を利用する。

| 種別 | 内容 |
|---|---|
| 株価 | 日足OHLCV |
| 移動平均 | 5日、25日、75日 |
| 出来高 | 出来高、出来高平均比 |
| 変化率 | 1日、5日、20日騰落率 |
| ボラティリティ | 20日ボラティリティ |
| ブレイク判定 | 20日高値更新、20日安値更新 |
| ギャップ | ギャップアップ、ギャップダウン |
| イベント | 決算予定、直近開示 |
| 市況 | 取得可能であれば日経平均、TOPIX、業種指数 |

---

## 9. LLM設計

### 9.1 基本方針

LLMはローカル実行を基本とし、初期実装ではOllamaを利用する。

LLMには、株価計算や移動平均計算は行わせない。

LLMの責務は以下とする。

- Python側で計算済みの特徴量を読む
- 短期売買判断を行う
- 判断理由を生成する
- 買い条件を生成する
- 撤退条件を生成する
- リスク要因を整理する
- JSON形式で構造化出力する

---

### 9.2 LLM Provider設計

LLM呼び出し部分は抽象化する。

```text
LLMProvider
  ├─ OllamaProvider
  ├─ MockProvider
  └─ FutureExternalProvider
```

MVPでは以下を実装する。

| Provider | 用途 |
|---|---|
| OllamaProvider | 実際のローカルLLM判断 |
| MockProvider | 開発・テスト用の固定レスポンス |

---

### 9.3 LLM入力形式

LLMには以下のような構造化データを渡す。

```json
{
  "company": {
    "security_code": "7203",
    "name": "トヨタ自動車",
    "market": "Prime",
    "industry": "輸送用機器"
  },
  "as_of": "2026-04-25",
  "price_features": {
    "last_close": 3000,
    "change_1d_pct": 1.2,
    "change_5d_pct": 4.5,
    "change_20d_pct": 8.3,
    "ma_5": 2950,
    "ma_25": 2820,
    "ma_75": 2700,
    "price_vs_ma_5_pct": 1.7,
    "price_vs_ma_25_pct": 6.4,
    "price_vs_ma_75_pct": 11.1,
    "volume_ratio_5d": 1.6,
    "volatility_20d": 0.025,
    "trend_short": "up",
    "trend_middle": "up",
    "recent_high_break": true,
    "recent_low_break": false,
    "gap_up": false,
    "gap_down": false
  },
  "event_context": {
    "has_recent_disclosure": true,
    "recent_disclosure_summaries": [
      "通期業績予想を上方修正"
    ],
    "days_to_earnings": 12
  },
  "market_context": {
    "nikkei_trend": "up",
    "topix_trend": "up",
    "sector_trend": "neutral"
  }
}
```

---

### 9.4 LLM出力形式

LLM出力は自由文ではなく、JSON形式とする。

```json
{
  "judgement_type": "short_term",
  "action": "WATCH_BUY",
  "confidence": 0.68,
  "time_horizon": "several_days_to_3_weeks",
  "summary": "短期では上昇基調だが、直近上昇後のため即時買いではなく押し目監視が妥当。",
  "positive_factors": [
    "終値が5日・25日・75日移動平均線を上回っている",
    "出来高が5日平均比で増加している",
    "直近高値を更新している"
  ],
  "negative_factors": [
    "短期的な上昇率が高く、追いかけ買いのリスクがある",
    "直近の適時開示確認が不十分"
  ],
  "entry_conditions": [
    "25日移動平均線を割らずに反発する",
    "出来高を伴って直近高値を再更新する"
  ],
  "exit_conditions": [
    "終値で25日移動平均線を明確に下回る",
    "出来高を伴う大陰線が出る",
    "悪材料の適時開示が出る"
  ],
  "risk_notes": [
    "株価データは日次更新でありリアルタイムではない",
    "短期判断のため決算・業績の長期評価は限定的"
  ]
}
```

---

### 9.5 JSON Schema

LLM出力は以下のJSON Schemaに準拠させる。

```json
{
  "type": "object",
  "required": [
    "judgement_type",
    "action",
    "confidence",
    "time_horizon",
    "summary",
    "positive_factors",
    "negative_factors",
    "entry_conditions",
    "exit_conditions",
    "risk_notes"
  ],
  "properties": {
    "judgement_type": {
      "type": "string",
      "enum": ["short_term"]
    },
    "action": {
      "type": "string",
      "enum": [
        "BUY",
        "WATCH_BUY",
        "NO_TRADE",
        "WATCH_SELL",
        "SELL",
        "INSUFFICIENT_DATA"
      ]
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "time_horizon": {
      "type": "string"
    },
    "summary": {
      "type": "string"
    },
    "positive_factors": {
      "type": "array",
      "items": { "type": "string" }
    },
    "negative_factors": {
      "type": "array",
      "items": { "type": "string" }
    },
    "entry_conditions": {
      "type": "array",
      "items": { "type": "string" }
    },
    "exit_conditions": {
      "type": "array",
      "items": { "type": "string" }
    },
    "risk_notes": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

---

## 10. 短期判断プロンプト

MVPでは以下のプロンプトを基本とする。

```text
あなたは日本株の短期売買判断エンジンです。
入力された情報だけを使い、日足ベースで数日〜3週間程度の短期判断を行ってください。

目的:
- BUY / WATCH_BUY / NO_TRADE / WATCH_SELL / SELL / INSUFFICIENT_DATA のいずれかを選ぶ
- 判断理由を簡潔に示す
- 買い条件と撤退条件を示す
- データ不足やリスクがある場合は無理に判断しない

制約:
- リアルタイム株価ではない前提で判断する
- 入力にない事実を作らない
- 財務・決算の長期評価は行わない
- テクニカル指標、出来高、直近イベントを優先する
- 判断材料が弱い場合は NO_TRADE または INSUFFICIENT_DATA を選ぶ
- 必ず指定されたJSON Schemaに従って出力する

判断基準:
- 上昇トレンド、出来高増加、高値更新、好材料が揃う場合は BUY または WATCH_BUY
- 上昇後の過熱感が強い場合は WATCH_BUY または NO_TRADE
- 下降トレンド、安値更新、悪材料がある場合は WATCH_SELL または SELL
- トレンドが不明瞭な場合は NO_TRADE
- データ鮮度や開示確認が不十分な場合は INSUFFICIENT_DATA を検討する
```

---

## 11. データベース設計

### 11.1 SQLite設定

SQLiteでは以下の設定を利用する。

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```

---

### 11.2 テーブル一覧

MVPでは以下のテーブルを利用する。

```text
companies
price_bars
technical_indicators
watchlists
disclosures
documents
ai_prompt_templates
ai_judgements
data_update_logs
app_settings
```

---

### 11.3 companies

銘柄マスタ。

```sql
CREATE TABLE companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    security_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    market TEXT,
    sector TEXT,
    industry TEXT,
    fiscal_year_end TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

---

### 11.4 price_bars

株価データ。

```sql
CREATE TABLE price_bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    timeframe TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    adjusted_close REAL,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, timeframe, date, source)
);

CREATE INDEX idx_price_bars_company_timeframe_date
ON price_bars(company_id, timeframe, date);
```

---

### 11.5 technical_indicators

計算済みテクニカル指標。

```sql
CREATE TABLE technical_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    timeframe TEXT NOT NULL,
    date TEXT NOT NULL,

    ma_5 REAL,
    ma_25 REAL,
    ma_75 REAL,
    volume_ma_5 REAL,
    volume_ma_25 REAL,
    rsi_14 REAL,
    volatility_20 REAL,

    trend_short TEXT,
    trend_middle TEXT,
    recent_high_break INTEGER,
    recent_low_break INTEGER,
    gap_up INTEGER,
    gap_down INTEGER,

    features_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, timeframe, date)
);

CREATE INDEX idx_technical_indicators_company_timeframe_date
ON technical_indicators(company_id, timeframe, date);
```

---

### 11.6 watchlists

ウォッチリスト。

```sql
CREATE TABLE watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    list_name TEXT NOT NULL DEFAULT 'default',
    memo TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, list_name)
);
```

---

### 11.7 disclosures

適時開示・決算短信など。

```sql
CREATE TABLE disclosures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    title TEXT NOT NULL,
    document_type TEXT,
    published_at TEXT,
    source TEXT,
    url TEXT,
    local_path TEXT,
    summary TEXT,
    importance_score REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX idx_disclosures_company_published_at
ON disclosures(company_id, published_at);
```

---

### 11.8 documents

EDINET、有報、IR資料、PDFなど。

```sql
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    source TEXT NOT NULL,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    url TEXT,
    local_path TEXT,
    raw_text_path TEXT,
    extracted_text_status TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);
```

---

### 11.9 ai_prompt_templates

LLMプロンプトテンプレート。

```sql
CREATE TABLE ai_prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    judgement_type TEXT NOT NULL,
    version TEXT NOT NULL,
    template_text TEXT NOT NULL,
    model_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,

    UNIQUE(name, version)
);
```

---

### 11.10 ai_judgements

AI判断履歴。

```sql
CREATE TABLE ai_judgements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    judgement_type TEXT NOT NULL,
    target_date TEXT NOT NULL,

    action TEXT NOT NULL,
    confidence REAL,
    time_horizon TEXT,

    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,

    prompt_template_id INTEGER,
    model_provider TEXT NOT NULL DEFAULT 'ollama',
    model_name TEXT,
    model_options_json TEXT,

    data_as_of TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (prompt_template_id) REFERENCES ai_prompt_templates(id)
);

CREATE INDEX idx_ai_judgements_company_target_date
ON ai_judgements(company_id, target_date);

CREATE INDEX idx_ai_judgements_action
ON ai_judgements(action);
```

---

### 11.11 data_update_logs

データ更新ログ。

```sql
CREATE TABLE data_update_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    message TEXT,
    metadata_json TEXT
);
```

---

### 11.12 app_settings

アプリ設定。

```sql
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

---

## 12. ファイル保存設計

SQLiteにはPDFや長文テキストを直接保存せず、ローカルファイルとして保存し、DBにはパスを保存する。

```text
data/
  app.db
  raw/
    prices/
    disclosures/
    edinet/
    news/
  documents/
    7203/
      tdnet/
      edinet/
      ir/
  extracted_text/
    7203/
      document_001.txt
  logs/
```

---

## 13. バッチ処理設計

### 13.1 バッチ一覧

```text
daily_update
  ├─ update_company_master
  ├─ update_prices
  ├─ calculate_technical_indicators
  ├─ update_disclosures
  ├─ summarize_disclosures
  └─ run_short_term_judgements
```

---

### 13.2 株価更新処理

```text
1. 対象銘柄を取得
2. データソースから日足データを取得
3. price_barsに保存
4. 既存データと重複する場合は更新
5. data_update_logsに結果を保存
```

---

### 13.3 テクニカル指標計算

```text
1. price_barsから日足データを取得
2. 5日MAを計算
3. 25日MAを計算
4. 75日MAを計算
5. 出来高5日平均を計算
6. 出来高25日平均を計算
7. 20日ボラティリティを計算
8. 20日高値更新を判定
9. 20日安値更新を判定
10. ギャップアップ・ギャップダウンを判定
11. technical_indicatorsに保存
```

---

### 13.4 AI短期判断処理

```text
1. ウォッチリスト銘柄を取得
2. 最新の株価・テクニカル指標を取得
3. 直近開示・イベント情報を取得
4. LLM入力JSONを生成
5. ai_prompt_templatesから有効なプロンプトを取得
6. OllamaProviderでローカルLLMを呼び出す
7. JSON Schemaで出力を検証
8. ai_judgementsに保存
9. 失敗時はdata_update_logsに記録
```

---

## 14. API設計

### 14.1 銘柄

```text
GET /companies/search
GET /companies/{security_code}
```

---

### 14.2 株価・チャート

```text
GET /companies/{security_code}/prices
GET /companies/{security_code}/chart
GET /companies/{security_code}/indicators
```

---

### 14.3 ウォッチリスト

```text
GET /watchlist
POST /watchlist
DELETE /watchlist/{id}
```

---

### 14.4 開示

```text
GET /companies/{security_code}/disclosures
POST /companies/{security_code}/disclosures
```

---

### 14.5 AI判断

```text
GET /companies/{security_code}/ai-judgements
POST /companies/{security_code}/ai-judgements/run
GET /ai-judgements/latest
```

---

### 14.6 バッチ・ジョブ

```text
POST /jobs/update-prices
POST /jobs/calculate-indicators
POST /jobs/update-disclosures
POST /jobs/run-short-term-judgements
GET /jobs/logs
```

---

## 15. 画面設計

### 15.1 画面一覧

MVPでは以下の画面を実装する。

```text
1. ウォッチリスト画面
2. 銘柄詳細画面
3. AI判断履歴画面
4. 設定画面
```

---

### 15.2 ウォッチリスト画面

ウォッチリスト画面では、監視銘柄の短期状態を一覧表示する。

表示項目は以下。

| 項目 | 内容 |
|---|---|
| 証券コード | 銘柄コード |
| 会社名 | 銘柄名 |
| 終値 | 最新終値 |
| 前日比 | 1日騰落率 |
| 5日変化率 | 短期騰落率 |
| 20日変化率 | 中期寄りの騰落率 |
| 25日線乖離率 | 短期トレンド確認 |
| 出来高倍率 | 5日平均比 |
| AI判断 | BUY / WATCH_BUY / NO_TRADE 等 |
| 信頼度 | LLM confidence |
| 最新開示 | 直近開示の有無 |

---

### 15.3 銘柄詳細画面

銘柄詳細画面では、チャートとAI判断を表示する。

```text
[銘柄ヘッダー]
- 証券コード
- 会社名
- 市場
- 業種
- 最新終値
- 前日比

[チャート]
- 日足ローソク足
- 5日MA
- 25日MA
- 75日MA
- 出来高

[短期AI判断]
- アクション
- 信頼度
- 判断要約
- ポジティブ要因
- ネガティブ要因
- 買い条件
- 撤退条件
- リスクメモ

[開示]
- 直近開示一覧
- 開示要約

[判断履歴]
- 過去のAI判断
- 判断後の株価確認
```

---

### 15.4 AI判断履歴画面

AI判断履歴画面では、過去のLLM判断を一覧表示する。

表示項目は以下。

| 項目 | 内容 |
|---|---|
| 判断日 | target_date |
| 銘柄 | company |
| 判断種別 | short_term |
| アクション | BUY等 |
| 信頼度 | confidence |
| モデル | model_name |
| 要約 | summary |
| 入力データ | input_json |
| 出力データ | output_json |

---

## 16. 短期テクニカル特徴量

MVPで利用する特徴量は以下。

| 特徴量 | 説明 |
|---|---|
| last_close | 最新終値 |
| change_1d_pct | 前日比 |
| change_5d_pct | 5日騰落率 |
| change_20d_pct | 20日騰落率 |
| ma_5 | 5日移動平均 |
| ma_25 | 25日移動平均 |
| ma_75 | 75日移動平均 |
| price_vs_ma_5_pct | 5日MA乖離率 |
| price_vs_ma_25_pct | 25日MA乖離率 |
| price_vs_ma_75_pct | 75日MA乖離率 |
| volume_ratio_5d | 出来高5日平均比 |
| volatility_20d | 20日ボラティリティ |
| trend_short | 短期トレンド |
| trend_middle | 中期寄りトレンド |
| recent_high_break | 20日高値更新 |
| recent_low_break | 20日安値更新 |
| gap_up | ギャップアップ |
| gap_down | ギャップダウン |

---

## 17. 判断ロジックの責務分離

### 17.1 Python側の責務

Python側では以下を担当する。

- 株価データ取得
- データ保存
- 欠損チェック
- 移動平均計算
- 出来高倍率計算
- 騰落率計算
- ボラティリティ計算
- 高値・安値更新判定
- ギャップ判定
- LLM入力JSON生成
- LLM出力JSON検証
- 判断履歴保存

---

### 17.2 LLM側の責務

LLM側では以下を担当する。

- 短期売買判断
- 判断理由の説明
- ポジティブ要因の整理
- ネガティブ要因の整理
- 買い条件の提示
- 撤退条件の提示
- リスクメモの生成

---

## 18. セーフティ設計

自分用ツールであっても、LLM判断には以下の安全装置を設ける。

### 18.1 データ鮮度チェック

最新株価データが古い場合、AI判断時に警告を付与する。

例。

```text
株価データが3営業日以上更新されていない場合、INSUFFICIENT_DATA または NO_TRADE を優先する。
```

---

### 18.2 判断材料不足チェック

以下の場合は、LLMに `INSUFFICIENT_DATA` を選ばせる。

- 株価データが不足している
- 移動平均が計算できない
- 出来高データが欠損している
- 直近データが古い
- 開示情報の取得状態が不明

---

### 18.3 決算直前チェック

決算予定日が近い場合は、リスクメモに明記する。

例。

```text
決算予定日まで5営業日以内の場合、BUY判定を慎重化する。
```

---

### 18.4 流動性チェック

出来高が極端に少ない銘柄は、リスクメモに明記する。

---

### 18.5 過熱感チェック

短期上昇率が高すぎる場合は、BUYではなくWATCH_BUYまたはNO_TRADEを優先する。

---

## 19. 非機能要件

### 19.1 パフォーマンス

| 項目 | 目標 |
|---|---|
| ウォッチリスト表示 | 1秒以内 |
| 銘柄詳細表示 | 2秒以内 |
| チャート表示 | 2秒以内 |
| AI判断生成 | 数秒〜数十秒以内 |
| 日次バッチ | 数分以内 |

---

### 19.2 可用性

- ローカル環境で単体動作する
- ネットワーク障害時も保存済みデータは閲覧可能
- LLMが動作していない場合もチャート・データ閲覧は可能
- バッチ失敗時はログを保存する

---

### 19.3 保守性

- データソースを差し替え可能にする
- LLM Providerを差し替え可能にする
- プロンプトテンプレートをDB管理する
- 判断履歴を保存し、後から検証可能にする

---

### 19.4 セキュリティ

個人用ツールであるため、初期段階では高度な認証は必須としない。

ただし、以下は考慮する。

- ローカルホストでの利用を基本とする
- 外部公開しない
- APIキーをコードに直書きしない
- 設定ファイルまたは環境変数で管理する
- 将来的に外部公開する場合は認証を追加する

---

## 20. 設定項目

アプリ設定として以下を管理する。

| 設定 | 内容 |
|---|---|
| default_llm_provider | 既定のLLM Provider |
| ollama_base_url | Ollama API URL |
| ollama_model_name | 使用モデル名 |
| judgement_temperature | LLM temperature |
| default_timeframe | 既定チャート足 |
| data_source_price | 株価データソース |
| update_schedule | 更新スケジュール |
| watchlist_default | 既定ウォッチリスト |

---

## 21. 実装順序

### Step 1: 基盤構築

- FastAPIプロジェクト作成
- SQLite接続
- DBマイグレーション
- companiesテーブル作成
- watchlistsテーブル作成

---

### Step 2: 株価データ管理

- price_barsテーブル作成
- 株価取得処理実装
- 日足保存処理実装
- チャートAPI実装

---

### Step 3: テクニカル指標

- technical_indicatorsテーブル作成
- MA計算
- 出来高倍率計算
- 騰落率計算
- 高値・安値更新判定
- ギャップ判定

---

### Step 4: ローカルLLM連携

- Ollama接続確認
- OllamaProvider実装
- MockProvider実装
- ai_prompt_templates作成
- ai_judgements作成
- JSON Schema検証実装

---

### Step 5: AI短期判断

- LLM入力JSON生成
- 短期判断プロンプト登録
- Ollama呼び出し
- AI判断保存
- AI判断取得API実装

---

### Step 6: UI実装

- ウォッチリスト画面
- 銘柄詳細画面
- チャート表示
- AI判断カード
- 判断履歴画面

---

### Step 7: 開示情報

- disclosuresテーブル作成
- 直近開示登録
- 開示一覧表示
- 開示要約の保存

---

## 22. 将来拡張

### 22.1 中長期判断

将来的に、プロンプトと判断種別を追加することで中長期判断に対応する。

```text
judgement_type:
- short_term
- mid_long_term
```

中長期判断では以下を扱う。

- 決算推移
- 売上成長
- 利益率
- EPS
- 配当
- 財務安全性
- 業界動向
- EDINET情報
- 有報のリスク情報

---

### 22.2 バックテスト

AI判断後の株価推移を記録し、判断精度を検証する。

検証項目。

- BUY判定後の5営業日リターン
- BUY判定後の20営業日リターン
- SELL判定後の下落率
- WATCH_BUYからBUYへの移行率
- NO_TRADE判定の妥当性

---

### 22.3 PWA対応

WebアプリをPWA化し、スマートフォンから利用できるようにする。

---

### 22.4 デスクトップアプリ化

Tauriを用いて、ローカルデスクトップアプリ化を検討する。

---

### 22.5 外部LLM対応

将来的に、必要に応じてOpenAI API等の外部LLMを利用可能にする。

そのため、LLM Provider抽象化は維持する。

---

## 23. 現時点の確定事項

現時点で確定している設計方針は以下。

```text
- 自分用ツールとして作る
- 日本株を対象とする
- 初期判断対象は短期売買とする
- LLMに最終判断までさせる
- ただしLLMには計算をさせない
- Python側で特徴量を生成する
- ローカルLLMを利用する
- 初期LLM実行基盤はOllamaとする
- データベースはSQLiteを用いる
- リアルタイム株価は扱わない
- 有料サービスは原則使わない
- 初期UIはWebアプリとする
- 将来的にPWAまたはTauri化を検討する
```

---

## 24. 未確定事項

今後決めるべき事項は以下。

```text
- 使用するローカルLLMモデル
- 株価データの主データソース
- 適時開示の取得方法
- UIデザイン方針
- バッチ実行方式
- PWA化の優先度
- バックテスト機能の実装時期
- 中長期判断機能の追加時期
```

---

## 25. MVPの完成条件

MVPは、以下が満たされた状態を完成とする。

```text
1. ウォッチリストに銘柄を登録できる
2. 登録銘柄の日足チャートを表示できる
3. 5日・25日・75日移動平均を表示できる
4. 出来高を表示できる
5. 短期テクニカル特徴量を計算できる
6. ローカルLLMに短期判断を実行させられる
7. BUY / WATCH_BUY / NO_TRADE / WATCH_SELL / SELL / INSUFFICIENT_DATA のいずれかが返る
8. 判断理由、買い条件、撤退条件、リスクメモが保存される
9. 過去のAI判断履歴を確認できる
10. SQLite上に判断履歴と入力データが保存される
```

---