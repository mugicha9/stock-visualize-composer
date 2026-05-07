import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ActionBadge } from "@/components/ActionBadge";
import { ChartPanel } from "@/components/ChartPanel";
import { DisclosureForm } from "@/components/DisclosureForm";
import { ExternalPromptButton } from "@/components/ExternalPromptButton";
import { RunJudgementButton } from "@/components/RunJudgementButton";
import { apiGet } from "@/lib/api";
import { formatConfidence, formatNumber, formatPct, formatPrice } from "@/lib/format";
import type { ChartResponse, Company, Disclosure, Judgement, TechnicalFeatures } from "@/lib/types";

type Props = {
  params: {
    securityCode: string;
  };
  searchParams?: {
    timeframe?: string;
  };
};

const chartTimeframes = ["1d", "1w", "1mo"] as const;

export default async function CompanyDetailPage({ params, searchParams }: Props) {
  const securityCode = decodeURIComponent(params.securityCode);
  const timeframe = chartTimeframes.includes(searchParams?.timeframe as (typeof chartTimeframes)[number])
    ? (searchParams?.timeframe as (typeof chartTimeframes)[number])
    : "1d";
  const [company, chart, judgements, disclosures] = await Promise.all([
    apiGet<Company>(`/companies/${securityCode}`),
    apiGet<ChartResponse>(`/companies/${securityCode}/chart?timeframe=${timeframe}&limit=180`),
    apiGet<Judgement[]>(`/companies/${securityCode}/ai-judgements?limit=20`),
    apiGet<Disclosure[]>(`/companies/${securityCode}/disclosures?limit=10`)
  ]);
  const features = company.latest_indicator?.features ?? {};
  const latest = judgements[0];

  return (
    <>
      <section className="page-head detail-head">
        <div>
          <Link href="/" className="back-link">
            <ArrowLeft size={16} aria-hidden="true" />
            <span>Watchlist</span>
          </Link>
          <p className="eyebrow">{company.security_code}</p>
          <h1>{company.name}</h1>
          <p className="meta-line">{[company.market, company.sector, company.industry].filter(Boolean).join(" / ")}</p>
        </div>
        <div className="detail-head-actions">
          <RunJudgementButton securityCode={securityCode} />
          <ExternalPromptButton securityCode={securityCode} />
        </div>
      </section>

      <section className="metric-strip">
        <Metric label="終値" value={formatPrice(features.last_close ?? company.latest_price?.close)} />
        <Metric label="前日比" value={formatPct(features.change_1d_pct)} tone={Number(features.change_1d_pct ?? 0) >= 0 ? "positive" : "negative"} />
        <Metric label="5日" value={formatPct(features.change_5d_pct)} tone={Number(features.change_5d_pct ?? 0) >= 0 ? "positive" : "negative"} />
        <Metric label="20日" value={formatPct(features.change_20d_pct)} tone={Number(features.change_20d_pct ?? 0) >= 0 ? "positive" : "negative"} />
        <Metric label="25日乖離" value={formatPct(features.price_vs_ma_25_pct)} tone={Number(features.price_vs_ma_25_pct ?? 0) >= 0 ? "positive" : "negative"} />
        <Metric label="出来高倍率" value={features.volume_ratio_5d ? `${features.volume_ratio_5d.toFixed(2)}x` : "-"} />
      </section>

      <section className="section">
        <div className="section-title-row">
          <h2>チャート</h2>
          <TimeframeTabs securityCode={securityCode} timeframe={timeframe} />
        </div>
        <ChartPanel bars={chart.bars} />
      </section>

      <section className="detail-grid">
        <div className="panel">
          <div className="section-title-row">
            <h2>中長期AI判断</h2>
            <ActionBadge action={latest?.action ?? latest?.output?.action} />
          </div>
          {latest?.output ? <JudgementDetail judgement={latest} /> : <p className="empty-text">AI判断なし</p>}
        </div>
        <div className="panel">
          <h2>特徴量</h2>
          <FeatureList features={features} />
        </div>
      </section>

      <section className="detail-grid">
        <div className="panel">
          <h2>開示</h2>
          <div className="list-stack">
            {disclosures.map((item) => (
              <article className="list-item" key={item.id}>
                <div className="list-item-head">
                  <strong>{item.title}</strong>
                  <span>{item.published_at ?? "-"}</span>
                </div>
                <p>{item.summary ?? "-"}</p>
              </article>
            ))}
            {disclosures.length === 0 ? <p className="empty-text">開示なし</p> : null}
          </div>
        </div>
        <div className="panel">
          <h2>開示登録</h2>
          <DisclosureForm securityCode={securityCode} />
        </div>
      </section>

      <section className="section">
        <h2>判断履歴</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>判断日</th>
                <th>対象日</th>
                <th>アクション</th>
                <th>信頼度</th>
                <th>モデル</th>
                <th>要約</th>
              </tr>
            </thead>
            <tbody>
              {judgements.map((item) => (
                <tr key={item.id}>
                  <td>{item.created_at.slice(0, 10)}</td>
                  <td>{item.target_date}</td>
                  <td>
                    <ActionBadge action={item.action ?? item.output?.action} />
                  </td>
                  <td className="number">{formatConfidence(item.confidence)}</td>
                  <td>{[item.model_provider, item.model_name].filter(Boolean).join(" / ")}</td>
                  <td>{item.output?.summary ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function TimeframeTabs({ securityCode, timeframe }: { securityCode: string; timeframe: "1d" | "1w" | "1mo" }) {
  const labels = [
    ["1d", "日足"],
    ["1w", "週足"],
    ["1mo", "月足"]
  ] as const;
  return (
    <div className="segmented">
      {labels.map(([value, label]) => (
        <Link
          key={value}
          href={`/companies/${securityCode}?timeframe=${value}`}
          className={timeframe === value ? "active" : undefined}
        >
          {label}
        </Link>
      ))}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function JudgementDetail({ judgement }: { judgement: Judgement }) {
  const output = judgement.output;
  if (!output) return null;
  return (
    <div className="judgement-detail">
      <p className="summary">{output.summary}</p>
      <div className="factor-grid">
        <FactorList title="ポジティブ" items={output.positive_factors} />
        <FactorList title="ネガティブ" items={output.negative_factors} />
        <FactorList title="買い条件" items={output.entry_conditions} />
        <FactorList title="撤退条件" items={output.exit_conditions} />
        <FactorList title="リスク" items={output.risk_notes} />
      </div>
      <p className="meta-line">confidence {formatConfidence(output.confidence)} / {judgement.model_provider}</p>
    </div>
  );
}

function FactorList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="factor">
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function FeatureList({ features }: { features: TechnicalFeatures }) {
  const rows = [
    ["MA5", formatPrice(features.ma_5)],
    ["MA25", formatPrice(features.ma_25)],
    ["MA75", formatPrice(features.ma_75)],
    ["MA5乖離", formatPct(features.price_vs_ma_5_pct)],
    ["MA75乖離", formatPct(features.price_vs_ma_75_pct)],
    ["20日ボラ", formatNumber(features.volatility_20d, 4)],
    ["短期トレンド", features.trend_short ?? "-"],
    ["中期トレンド", features.trend_middle ?? "-"],
    ["高値更新", features.recent_high_break ? "Yes" : "No"],
    ["安値更新", features.recent_low_break ? "Yes" : "No"]
  ];
  return (
    <dl className="feature-list">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
