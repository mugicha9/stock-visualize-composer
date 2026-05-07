"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";

type PipelineStep = {
  id: string;
  title: string;
  input: string;
  process: string;
  output: string;
  settings: string[];
  issue?: string;
  proposal?: string;
};

const CURRENT_STEPS: PipelineStep[] = [
  {
    id: "local-llm-connection",
    title: "ローカルLLM接続",
    input: "config/app_settings.json",
    process: "llama.cpp serverのOpenAI互換APIへ接続し、モデル名とサンプリング設定を読み込みます。",
    output: "llama.cpp /v1/chat/completions",
    settings: ["default_llm_provider", "llama_cpp_base_url", "llama_cpp_model_name"]
  },
  {
    id: "fetch-company",
    title: "企業取得",
    input: "銘柄コード",
    process: "株価、会社情報、決算スナップショット、適時開示、企業ニュースを取得します。企業ニュースは会社別キーワードで保存前に絞り込みます。",
    output: "price_bars / company_financials / disclosures / news_articles / company_news_profiles",
    settings: [
      "company_news_fetch_limit",
      "company_news_keyword_profile_enabled",
      "company_news_relevance_min_score",
      "news_summary_on_update",
      "prompt_company_news_profile_system"
    ]
  },
  {
    id: "fetch-global",
    title: "全体取得",
    input: "公式RSS",
    process: "経済、政策、金融、地政学ニュースを共有テーブルへ保存します。",
    output: "global_news",
    settings: ["global_news_fetch_limit_per_source"]
  },
  {
    id: "required-context",
    title: "必須情報",
    input: "会社マスタ、決算、指標、価格特徴量、PDF抽出済み開示",
    process: "会社情報、決算情報、PER/PBR/ROE/配当利回り、重要開示PDFの抽出テキストを判断入力へ入れます。",
    output: "fundamental_digest / price_features / documents",
    settings: ["disclosure_pdf_extract_on_update", "disclosure_pdf_extract_limit", "disclosure_pdf_max_pages"]
  },
  {
    id: "rank-news",
    title: "ニュース選別",
    input: "企業ニュースと全体ニュースのタイトル",
    process: "対象企業にとって重要な記事をLLMまたはキーワードで選びます。",
    output: "selected_company_news / selected_global_news",
    settings: [
      "llm_news_selection_max_company",
      "llm_news_selection_max_global",
      "llama_cpp_model_name",
      "prompt_news_relevance_system",
      "prompt_news_relevance_policy"
    ]
  },
  {
    id: "summarize",
    title: "本文要約",
    input: "選別済み記事の本文またはURL",
    process: "必要な記事だけ本文取得と要約を行い、コンテキストを圧縮します。",
    output: "summary",
    settings: ["news_summary_max_items", "news_summary_timeout_seconds", "prompt_news_summary_system", "prompt_news_summary_task"]
  },
  {
    id: "signals",
    title: "Signal Card",
    input: "必須情報、選別ニュース、テクニカル特徴量",
    process: "technical / fundamental / news / market の材料を方向・影響度・鮮度に変換します。",
    output: "signal_cards",
    settings: []
  },
  {
    id: "packet",
    title: "Context Packet",
    input: "Signal Card",
    process: "LLMへ渡す最小コンテキストへ集約します。",
    output: "context_packet",
    settings: ["llama_cpp_context_length"]
  },
  {
    id: "judgement",
    title: "最終判断",
    input: "Context Packet",
    process: "中長期のBUY/WATCH/SELL系判断をJSONで生成します。",
    output: "ai_judgements",
    settings: [
      "default_llm_provider",
      "llama_cpp_model_name",
      "llama_cpp_temperature",
      "llama_cpp_top_p",
      "llama_cpp_top_k",
      "llm_judgement_max_attempts",
      "llm_grounding_auto_repair_enabled",
      "prompt_final_judgement_user_instruction",
      "prompt_final_judgement_repair_instruction"
    ]
  }
];

const PROPOSED_STEPS: PipelineStep[] = [
  {
    id: "source-events",
    title: "Source Event Store",
    input: "RSS / HTML / API / PDF",
    process: "企業ニュース、全体ニュース、適時開示、決算資料を1つのイベント形式へ正規化します。scope、company_id、information_date、content_hashで重複を抑えます。",
    output: "source_events",
    settings: ["company_news_fetch_limit", "global_news_fetch_limit_per_source"],
    issue: "現在はテーブルごとに形式が違い、判断時に何を使ったか追跡しづらいです。",
    proposal: "全情報の入口を統一し、同じURL・同じタイトル・同じ本文hashを再保存しない構成にします。"
  },
  {
    id: "triage",
    title: "Triage",
    input: "source_eventsのタイトル、媒体、カテゴリ",
    process: "低価値な定型記事を除外し、企業別・全体別に relevance / materiality / action を付けます。ルールで高速に落とし、境界例だけLLMを使います。",
    output: "event_triage",
    settings: ["llm_news_selection_max_company", "llm_news_selection_max_global"],
    issue: "選別結果がContext作成過程に埋もれ、なぜ採用されたか後から確認しにくいです。",
    proposal: "ignore / title_only / summarize / must_include を保存し、UIとバックテストで同じ選別結果を再利用します。"
  },
  {
    id: "summaries",
    title: "Versioned Summary",
    input: "triage済みイベント本文、PDF抽出テキスト",
    process: "本文要約をイベント単位で保存します。summary_type、prompt_version、model_name、language、created_atを持たせます。",
    output: "event_summaries",
    settings: ["news_summary_max_items", "news_summary_timeout_seconds", "news_summary_provider"],
    issue: "今はニューステーブルのsummaryに直接入るため、モデル変更時の比較が難しいです。",
    proposal: "同じ記事に対する要約をバージョン管理し、再要約・比較・削除を安全にします。"
  },
  {
    id: "signal-cards",
    title: "Persistent Signal Card",
    input: "価格特徴量、財務指標、要約済みイベント",
    process: "technical / fundamental / disclosure / company_news / market に分け、direction、impact、confidence、freshness、evidence_refsを保存します。",
    output: "signal_cards",
    settings: [],
    issue: "現在のSignal Cardは推論直前に生成され、DBに残りません。",
    proposal: "Cardを永続化して、判断履歴・バックテスト・UIで同じ根拠を参照できるようにします。"
  },
  {
    id: "packet-builder",
    title: "Context Packet Builder",
    input: "signal_cards",
    process: "as_ofとtoken budgetに基づき、採用Cardと除外Cardを決めます。採用理由、除外理由、token見積もりを保存します。",
    output: "context_packets",
    settings: ["llama_cpp_context_length"],
    issue: "未来情報遮断はありますが、最終的にどのCardを落としたかが見えません。",
    proposal: "included_signal_ids / excluded_signal_ids を持つPacketを保存し、判断を完全に再現できるようにします。"
  },
  {
    id: "final-judgement",
    title: "Grounded Judgement",
    input: "context_packets",
    process: "最終LLMにはContext Packetだけを渡します。出力には used_signal_ids と unsupported_claims を含め、検査に落ちた場合は修正プロンプトを走らせます。",
    output: "ai_judgements",
    settings: ["default_llm_provider", "llama_cpp_model_name", "llama_cpp_temperature"],
    issue: "現在は出力JSONがCard IDを明示しないため、根拠と結論の結びつきが弱いです。",
    proposal: "結論の各理由に signal_id を紐付け、UIで理由から元ニュース・開示へ辿れるようにします。"
  },
  {
    id: "evaluation",
    title: "Replay / Backtest",
    input: "context_packets / ai_judgements",
    process: "バックテストは判断日のPacketを使い、information_date <= as_of をDB制約として検証します。",
    output: "backtest_runs / evaluation_metrics",
    settings: [],
    issue: "期間ごとの情報取得と判断入力の監査がまだ弱いです。",
    proposal: "Packet ID単位で売買判断を再実行し、モデル変更前後の成績を比較します。"
  }
];

const MODES = {
  current: {
    label: "現行",
    description: "現在の実装は、判断時に保存済み入力からSignal CardとContext Packetを生成してLLMへ渡します。",
    steps: CURRENT_STEPS
  },
  proposal: {
    label: "提案 v2",
    description: "提案仕様では、情報、要約、Signal Card、Context Packetを永続化し、判断根拠を完全に監査できる形へ寄せます。",
    steps: PROPOSED_STEPS
  }
} as const;

export function PipelineExplorer() {
  const [mode, setMode] = useState<keyof typeof MODES>("current");
  const steps = MODES[mode].steps;
  const [activeId, setActiveId] = useState(steps[0].id);
  const active = steps.find((step) => step.id === activeId) ?? steps[0];

  function selectMode(nextMode: keyof typeof MODES) {
    setMode(nextMode);
    setActiveId(MODES[nextMode].steps[0].id);
  }

  return (
    <div className="pipeline-explorer">
      <div className="pipeline-main">
        <div className="pipeline-toolbar">
          <div>
            <p className="eyebrow">Pipeline Mode</p>
            <span>{MODES[mode].description}</span>
          </div>
          <div className="segmented pipeline-mode">
            <button className={mode === "current" ? "active" : undefined} type="button" onClick={() => selectMode("current")}>
              現行
            </button>
            <button className={mode === "proposal" ? "active" : undefined} type="button" onClick={() => selectMode("proposal")}>
              提案 v2
            </button>
          </div>
        </div>
        <div className="pipeline-flow">
          {steps.map((step, index) => (
            <div className="pipeline-step-wrap" key={step.id}>
              <button className={step.id === activeId ? "pipeline-step active" : "pipeline-step"} type="button" onClick={() => setActiveId(step.id)}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step.title}</strong>
              </button>
              {index < steps.length - 1 ? <ArrowRight className="pipeline-arrow" size={16} aria-hidden="true" /> : null}
            </div>
          ))}
        </div>
      </div>
      <div className="pipeline-detail panel">
        <p className="eyebrow">Pipeline Step</p>
        <h2>{active.title}</h2>
        <dl className="pipeline-detail-list">
          <div>
            <dt>入力</dt>
            <dd>{active.input}</dd>
          </div>
          <div>
            <dt>処理</dt>
            <dd>{active.process}</dd>
          </div>
          <div>
            <dt>出力</dt>
            <dd className="mono">{active.output}</dd>
          </div>
          <div>
            <dt>関連設定</dt>
            <dd>{active.settings.length ? active.settings.join(" / ") : "なし"}</dd>
          </div>
          {active.issue ? (
            <div>
              <dt>現状の課題</dt>
              <dd>{active.issue}</dd>
            </div>
          ) : null}
          {active.proposal ? (
            <div>
              <dt>提案</dt>
              <dd>{active.proposal}</dd>
            </div>
          ) : null}
        </dl>
      </div>
    </div>
  );
}
