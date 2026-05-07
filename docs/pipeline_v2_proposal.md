# LLM Pipeline v2 Proposal

## 目的

AI判断で使った情報、要約、Signal Card、Context Packet、最終判断を後から追跡できる形にする。バックテストでは、判断時点より未来の情報を使っていないことをDB上でも確認できるようにする。

## 現状の課題

- Signal Cardは判断直前に生成され、DBには残らない。
- ニュース、開示、全体ニュースの保存形式が分かれており、共通の採用理由を追いにくい。
- ニュース要約が元テーブルのsummaryへ直接保存され、モデルやプロンプト変更時の比較が難しい。
- AI判断の出力が、どのSignal Cardを根拠にしたかをIDで示していない。
- バックテストで使ったContext Packetを後から再現しづらい。

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
   - 判断日ごとの `context_packet_id` と `ai_judgement_id` を保存する。
   - `information_date <= as_of` を検査し、未来情報混入を検出する。

## 移行順

1. 現行の `input_json` からContext Packetを再生成してUI表示する。
2. `context_packets` を追加し、AI判断時にPacketを保存する。
3. 企業別ニュースキーワードプロファイルを導入し、保存前フィルタを強化する。
4. PDF本文抽出を導入し、OCRが必要な資料を識別する。
5. `signal_cards` を追加し、判断時に生成したCardを保存する。
6. ニュース・開示を `source_events` に統合する。
7. バックテストをPacket ID単位の再生方式へ移行する。
