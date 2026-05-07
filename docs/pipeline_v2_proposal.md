# LLM Pipeline v2

## 目的

AI判断で使った情報、要約、Signal Card、Context Packet、最終判断を後から追跡できる形にする。バックテストでは、判断時点より未来の情報を使っていないことをDB上でも確認できるようにする。

## 実装済み

- 判断時にContext Packetを生成し、`context_packets` に保存する。
- Context Packetに含めたSignal Cardを `signal_cards` に保存する。
- AI判断は `context_packet_id` を持ち、出力JSONに `used_signal_ids` を含める。
- `judgement_signal_links` に、最終判断で使われたSignal Cardを保存する。
- ニュース、開示、全体ニュースの入口を `source_events` に統合し、`event_key` と `content_hash` で重複保存を抑える。
- 取得・選別結果を `event_triage` に保存し、`ignore` / `title_only` / `summarize` / `must_include` を後から確認できるようにする。
- 要約を `event_summaries` に保存し、元イベントとモデル・要約種別を分けて扱う。
- Evidence UIでは、使われたSignal Cardを `USED` として展開表示する。
- Groundingの自動修復は文字列置換をやめ、再プロンプトを優先し、最後だけ安全な定型文へフォールバックする。
- ニュース、開示、全体ニュースの方向スコアは `material_assessment` を優先する。辞書スコアはLLM不可時の弱い補助に限定する。
- 保存量を抑えるため、Context Packetは銘柄ごとに `context_packet_retention_per_company` 件だけ保持する。

## 現在の課題

- バックテストは `information_date <= as_of` で未来情報を遮断するが、各ステップのContext Packet永続化は保存量抑制のためまだ行わない。

## 提案仕様

1. `source_events`
   - ニュース、適時開示、決算資料、全体ニュースを共通イベントとして保存する。
   - `scope`, `company_id`, `information_date`, `url`, `content_hash` を持たせ、重複保存を防ぐ。

2. `event_triage`
   - `ignore`, `title_only`, `summarize`, `must_include` を保存する。
   - 企業ごとに `company_terms`, `business_terms`, `material_terms`, `exclude_terms` を生成し、保存前に関連度を判定する。
   - 定型記事はルールで除外し、境界例だけLLMで重要度を付ける。

3. `event_summaries`
   - 要約をイベント単位でバージョン管理する。
   - 決算短信や決算説明資料PDFはまずテキスト抽出し、抽出できないPDFは `needs_ocr` としてOCRキューへ送る。
   - `prompt_version`, `model_name`, `summary_type`, `language` を保存する。

4. `signal_cards`
   - technical / fundamental / disclosure / company_news / market のCardを永続化する。
   - `direction_score`, `impact_score`, `confidence`, `freshness_score`, `evidence_refs` を持たせる。

5. `context_packets`
   - `as_of` と token budget に基づき、採用Cardと除外Cardを保存する。
   - `included_signal_ids`, `excluded_signal_ids`, `token_estimate`, `build_version` を持たせる。

6. `ai_judgements`
   - 最終判断は `context_packet_id` を参照する。
   - 出力に `used_signal_ids` を含め、理由と根拠Cardを結びつける。

7. `backtest_runs`
   - 保存量を抑える設定の下で、判断日ごとの `context_packet_id` と `ai_judgement_id` を保存できるようにする。
   - `information_date <= as_of` を検査し、未来情報混入を検出する。

## 移行順

1. 完了: 現行の `input_json` からContext Packetを再生成してUI表示する。
2. 完了: `context_packets` を追加し、AI判断時にPacketを保存する。
3. 完了: 企業別ニュースキーワードプロファイルを導入し、保存前フィルタを強化する。
4. 完了: PDF本文抽出を導入し、OCRが必要な資料を識別する。
5. 完了: `signal_cards` を追加し、判断時に生成したCardを保存する。
6. 完了: ニュース・開示を `source_events` に統合する。
7. 一部完了: バックテストは `source_events` の `information_date <= as_of` を使う。Packet ID単位の永続保存は未実装。
