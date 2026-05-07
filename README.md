# stock-visualize-composer

日本株の中長期判断を支援するローカル向けアプリです。JPX400を基本ユニバースとして、株価、会社情報、決算・開示、企業ニュース、共有ニュース、ローカルLLM判断、バックテストを扱います。

このツールは個人用の分析支援であり、投資助言や売買指示を目的としたものではありません。

## システム構成

```text
frontend/                    Next.js / React / TypeScript UI
backend/                     FastAPI / SQLite / データ取得 / LLMパイプライン
backend/app/schema.sql       SQLiteスキーマ
backend/app/services/        価格、企業情報、ニュース、LLM、バックテスト処理
backend/app/routers/         APIエンドポイント
config/app_settings.json     起動時に読み込むアプリ設定
data/app.db                  SQLite DB
scripts/dev-all.sh           FastAPI / Next.js / llama.cpp Docker 一括起動
scripts/dev-stop.sh          開発サーバーとllama.cppコンテナ停止
scripts/llama_cpp_docker.py  configからDocker起動コマンドを組み立てる
.node/                       WSL用Node.js配置先
memo.md                      初期設計メモ
pipeline_memo.md             LLMパイプライン設計メモ
```

## LLM構成

LLM実行基盤は `llama.cpp server` のDockerコンテナです。

アプリは `llama.cpp server` のOpenAI互換APIを使います。

```text
FastAPI
  -> http://127.0.0.1:10000/v1/chat/completions
  -> llama.cpp Docker
  -> /models/Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf
```

標準設定では、ホスト側のGGUFファイルをワークディレクトリ配下に置きます。

```text
data/llama-models/Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf
```

Docker内では `/models/Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf` として読み込みます。

## セットアップ

```bash
cp .env.example .env
make backend-install
make backend-init
make backend-seed
make frontend-install
```

GPU付きDockerでllama.cppを使うため、Docker、NVIDIA Driver、NVIDIA Container Toolkitが必要です。GGUFファイルは `llama_cpp_host_models_dir` に配置してください。

## 起動と停止

FastAPI、Next.js、llama.cpp Dockerをまとめて起動します。

```bash
make dev
```

起動後:

```text
API:        http://127.0.0.1:8000
API docs:   http://127.0.0.1:8000/docs
UI:         http://127.0.0.1:3000
llama.cpp:  http://127.0.0.1:10000
```

停止:

```bash
make dev-stop
```

個別操作:

```bash
make backend-dev
make frontend-dev
make llama-serve
make llama-stop
make llama-recreate
make llama-logs
make llama-command
```

`make llama-command` は、現在の `config/app_settings.json` から実行される `docker run` コマンドを表示します。設定を変えたあと既存コンテナへ反映する場合は `make llama-recreate` を使います。

## llama.cpp設定

主な設定は `config/app_settings.json` とUIの「設定」ページから変更できます。

```json
{
  "default_llm_provider": "llama_cpp",
  "news_summary_provider": "llama_cpp",
  "llama_cpp_base_url": "http://127.0.0.1:10000",
  "llama_cpp_model_name": "qwen3.6-35b-a3b",
  "llama_cpp_container_name": "llama-qwen36-cuda",
  "llama_cpp_image": "ghcr.io/ggml-org/llama.cpp:server-cuda",
  "llama_cpp_host_models_dir": "data/llama-models",
  "llama_cpp_container_models_dir": "/models",
  "llama_cpp_model_file": "Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf",
  "llama_cpp_port": "10000",
  "llama_cpp_container_port": "8080",
  "llama_cpp_context_length": "65536",
  "llama_cpp_gpu_layers": "auto",
  "llama_cpp_reasoning": "off",
  "llama_cpp_reasoning_budget": "0",
  "llama_cpp_temperature": "0.6",
  "llama_cpp_top_p": "0.95",
  "llama_cpp_top_k": "20",
  "llama_cpp_min_p": "0.0",
  "llama_cpp_presence_penalty": "0.0",
  "llama_cpp_repeat_penalty": "1.0"
}
```

提示されたDockerコマンドのうち、アプリで使う値は次のように整理しています。

```text
Docker/起動: container_name, image, docker_gpus, docker_env_json, host_models_dir, model_file, port
ポート: host側は `llama_cpp_port`、container内は `llama_cpp_container_port`。llama.cpp Docker image のhealthcheckに合わせ、container内は8080を使う
llama.cpp: alias, context_length, n_parallel, ncmoe, gpu_layers, mmap, chat_template_kwargs, reasoning
推論: temperature, top_p, top_k, min_p, presence_penalty, repeat_penalty
```

## 画面

- `Watchlist`: JPX400ウォッチリスト、チャート、会社・決算、ニュース、LLM判断
- `バックテスト`: 過去期間で判断と売買シミュレーション
- `Pipeline`: LLM判断パイプラインの可視化と関連設定の確認
- `AI履歴`: 保存済みAI判断の一覧
- `設定`: llama.cpp、ニュース取得件数、要約件数などの設定編集

メイン画面の主な操作:

- `全体取得`: 全銘柄で共有する経済・政策・金融・地政学ニュースを取得
- `企業取得`: 選択銘柄の株価、会社情報、開示、企業ニュースを取得
- `AI判断`: 選択銘柄の中長期判断を実行
- `外部AI`: 外部AIへ貼り付けるためのプロンプトを生成
- `企業全更新`: ウォッチリスト全銘柄の企業別データを更新
- `全AI判断`: ウォッチリスト全銘柄のAI判断を実行

## データ取得

企業別情報:

- 株価: Yahoo Finance chart API
- 会社情報: Yahoo!ファイナンス日本版を優先し、PER/PBR/EPS/BPS/配当利回りなどはYahoo Finance quote APIで補完
- 適時開示: Yahoo!ファイナンス日本版のTDnet由来PDFリンク
- 企業ニュース: Yahoo!ファイナンス日本版の銘柄ニュース

全体共有情報:

- NHK
- 経済産業省
- 日本銀行
- 内閣府
- 金融庁

共有ニュース、企業ニュース、適時開示は `source_events` に正規化して保存します。企業別イベントは `company_id` を持ち、経済・政策・地政学などの全体ニュースは `scope=global` として共有します。

## ニュース戦略

ニュースはすべてをLLMへ渡さず、段階的に圧縮します。

1. 取得時に低価値な定型記事を除外
2. 企業ニュース、適時開示、全体ニュースを `source_events` に正規化
3. 保存時・判断時の採否を `event_triage` に保存
4. AI判断時にタイトルと企業プロフィールで対象企業への重要度を選別
5. 選ばれた記事だけ本文取得・要約し、`event_summaries` に保存
6. 要約済み材料をSignal Card化し、判断時のContext Packetに紐付けて保存
7. Context Packetとして最終LLMへ渡し、使用したSignal Card IDを判断結果へ保存

重視する材料:

- 決算、業績修正、増配、減配、自社株買い
- M&A、提携、大型受注、設備投資
- 不正、訴訟、行政処分、規制
- 金利、為替、原油、LNG、関税
- 地政学、経済安全保障、サプライチェーン

## LLMパイプライン

判断時の流れは次の通りです。

```text
企業取得 / 全体取得
  ↓
source_eventsへニュース・開示・全体ニュースを正規化
  ↓
event_triageへ採否・重要度・理由を保存
  ↓
event_summariesへ本文要約・PDF抽出要約を保存
  ↓
会社情報・決算・PER/PBR/ROE・価格特徴量を必須入力化
  ↓
technical / fundamental / news / market のSignal Cardを生成
  ↓
Context Packetへ集約し、context_packets / signal_cardsへ保存
  ↓
llama.cppまたはMockProviderで中長期判断JSONを生成
  ↓
ai_judgements / judgement_signal_linksへ保存
```

## 主な設定キー

```text
default_llm_provider                  llama_cpp / mock
llama_cpp_base_url                    llama.cpp server API URL
llama_cpp_model_name                  判断・選別・要約に使うモデル名/alias
llama_cpp_timeout_seconds             最終判断のTimeout
llama_cpp_temperature                 temperature
llama_cpp_top_p / top_k / min_p       sampling設定
llama_cpp_presence_penalty            presence penalty
llama_cpp_repeat_penalty              repeat penalty
llama_cpp_container_name              Dockerコンテナ名
llama_cpp_image                       Docker image
llama_cpp_host_models_dir             ホスト側GGUF配置先
llama_cpp_container_models_dir        コンテナ側モデルDir
llama_cpp_model_file                  GGUFファイル名
llama_cpp_port                        ホスト側公開port
llama_cpp_container_port              コンテナ内port。通常は8080
llama_cpp_context_length              context length
llama_cpp_n_parallel                  並列slot数
llama_cpp_ncmoe                       MoE expert数
llama_cpp_gpu_layers                  GPUへoffloadするlayer数。autoで自動調整
llama_cpp_no_mmap                     falseならmmapを使い、モデルロード時のRAM負荷を抑える
llama_cpp_chat_template_kwargs        chat template kwargs JSON
llama_cpp_reasoning                   off / auto / on
llama_cpp_reasoning_budget            thinking token budget。0で即終了
llama_cpp_docker_env_json             Docker環境変数JSON
company_news_fetch_limit              企業ニュース保存件数
company_news_keyword_profile_enabled  企業別キーワードプロファイルを使うか
company_news_keyword_profile_refresh_days  企業別キーワードの再生成間隔
company_news_relevance_min_score      保存前の企業ニュース関連度下限
company_news_keyword_fetch_multiplier 保存前フィルタ用の候補取得倍率
global_news_fetch_limit_per_source    RSSごとの共有ニュース取得件数
llm_news_selection_max_company        判断時に選ぶ企業ニュース件数
llm_news_selection_max_global         判断時に選ぶ全体ニュース件数
news_summary_max_items                取得時に要約するニュース件数
news_summary_timeout_seconds          ニュース要約Timeout
news_summary_on_update                一括更新時に要約するか
disclosure_pdf_extract_on_update      開示PDFを取得時にテキスト抽出するか
disclosure_pdf_extract_limit          1回の開示更新で抽出する重要PDF数
disclosure_pdf_max_pages              PDFテキスト抽出の最大ページ数
disclosure_pdf_ocr_enabled            OCRを使うか。現状は予約設定
watchlist_default                     既定ウォッチリスト名
```

## API例

選択銘柄のデータ取得:

```bash
curl -X POST http://127.0.0.1:8000/companies/7203/fetch-data \
  -H 'Content-Type: application/json' \
  -d '{"price_range":"1y","include_prices":true,"include_financials":true,"include_disclosures":true,"include_news":true,"summarize_news":true}'
```

AI判断:

```bash
curl -X POST http://127.0.0.1:8000/companies/7203/ai-judgements/run \
  -H 'Content-Type: application/json' \
  -d '{"provider":"llama_cpp"}'
```

外部AI用プロンプト:

```bash
curl http://127.0.0.1:8000/companies/7203/ai-judgements/external-prompt
```

## バックテスト

バックテストでは、判断日より未来の情報を使わないように `information_date` / `published_at` / `as_of` で入力を制限します。判断は判断日終値までの情報で作り、売買は次の取引日の始値で約定する扱いです。

対応間隔:

- 1日
- 1週間
- 2週間
- 1か月

## 検証

```bash
.venv/bin/python -m compileall backend
make test
cd frontend && PATH="$(pwd)/../.node/bin:$PATH" npm run build
```

## 注意

- スクレイピングやRSS取得は取得元の構造変更で壊れる可能性があります。
- ニュース本文が取得できない場合はURL、タイトル、RSS要約を使います。
- LLM出力は投資判断の補助情報であり、最終判断は利用者が行ってください。
