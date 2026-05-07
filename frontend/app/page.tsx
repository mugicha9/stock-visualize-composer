import Link from "next/link";
import { Activity, Building2, FileText, Newspaper, SlidersHorizontal } from "lucide-react";
import { ActionBadge } from "@/components/ActionBadge";
import { AddWatchForm } from "@/components/AddWatchForm";
import { ChartPanel } from "@/components/ChartPanel";
import { CompanySearchForm } from "@/components/CompanySearchForm";
import { DashboardShell } from "@/components/DashboardShell";
import { ExternalPromptButton } from "@/components/ExternalPromptButton";
import { FetchCompanyDataButton } from "@/components/FetchCompanyDataButton";
import { FetchGlobalNewsButton } from "@/components/FetchGlobalNewsButton";
import { JudgementEvidencePanel } from "@/components/JudgementEvidencePanel";
import { RunJudgementButton } from "@/components/RunJudgementButton";
import { WatchlistBulkActions } from "@/components/WatchlistBulkActions";
import { apiGet } from "@/lib/api";
import { formatConfidence, formatPct, formatPrice } from "@/lib/format";
import type {
  ChartResponse,
  Company,
  Disclosure,
  FinancialMetric,
  FinancialSnapshot,
  GlobalNews,
  Judgement,
  JudgementContext,
  NewsArticle,
  WatchlistItem
} from "@/lib/types";

type Props = {
  searchParams?: {
    securityCode?: string;
    timeframe?: string;
    sort?: string;
  };
};

type Timeframe = "1d" | "1w";
type SortMode = "code" | "recommendation";

const actionRank: Record<string, number> = {
  BUY: 0,
  WATCH_BUY: 1,
  NO_TRADE: 2,
  WATCH_SELL: 3,
  SELL: 4,
  INSUFFICIENT_DATA: 5
};

export default async function WatchlistPage({ searchParams }: Props) {
  const sortMode: SortMode = searchParams?.sort === "recommendation" ? "recommendation" : "code";
  const rawItems = await apiGet<WatchlistItem[]>("/watchlist?list_name=JPX400").catch(() => []);
  const items = sortWatchlistItems(rawItems, sortMode);
  const selectedCode = searchParams?.securityCode || items[0]?.security_code;
  const timeframe: Timeframe = searchParams?.timeframe === "1w" ? "1w" : "1d";

  const [company, chart, judgements, disclosures, financials, news, globalNews]: [
    Company | null,
    ChartResponse | null,
    Judgement[],
    Disclosure[],
    FinancialSnapshot[],
    NewsArticle[],
    GlobalNews[]
  ] = selectedCode
    ? await Promise.all([
        apiGet<Company>(`/companies/${selectedCode}`).catch(() => null),
        apiGet<ChartResponse>(`/companies/${selectedCode}/chart?timeframe=${timeframe}&limit=160`).catch(() => null),
        apiGet<Judgement[]>(`/companies/${selectedCode}/ai-judgements?limit=10`).catch(() => []),
        apiGet<Disclosure[]>(`/companies/${selectedCode}/disclosures?limit=8`).catch(() => []),
        apiGet<FinancialSnapshot[]>(`/companies/${selectedCode}/financials?limit=1`).catch(() => []),
        apiGet<NewsArticle[]>(`/companies/${selectedCode}/news?limit=8`).catch(() => []),
        apiGet<GlobalNews[]>("/market-news?limit=8").catch(() => [])
      ])
    : [null, null, [], [], [], [], []];

  const latest = judgements[0];
  const latestContext = latest
    ? await apiGet<JudgementContext>(`/ai-judgements/${latest.id}/context`).catch(() => null)
    : null;
  const latestFinancial = financials[0];
  const features = company?.latest_indicator?.features ?? {};

  const watchPane = (
    <>
      <div className="watch-head">
        <div>
          <p className="eyebrow">Default Universe</p>
          <h1>JPX400</h1>
          <span className="subline">{items.length} symbols / daily data</span>
        </div>
      </div>
      <AddWatchForm />
      <WatchlistBulkActions listName="JPX400" />
      <WatchlistSortLinks sortMode={sortMode} selectedCode={selectedCode} timeframe={timeframe} />
      <div className="watch-list">
        {items.map((item) => {
          const itemFeatures = item.latest_indicator?.features ?? {};
          const active = item.security_code === selectedCode;
          return (
            <Link
              key={item.watchlist_id}
              href={`/?securityCode=${item.security_code}&timeframe=${timeframe}&sort=${sortMode}`}
              className={active ? "watch-row active" : "watch-row"}
            >
              <div className="watch-row-main">
                <strong>{item.security_code}</strong>
                <span>{item.name}</span>
              </div>
              <div className="watch-row-meta">
                <span>{formatPrice(itemFeatures.last_close ?? item.latest_price?.close)}</span>
                <span className={Number(itemFeatures.change_1d_pct ?? 0) >= 0 ? "positive" : "negative"}>
                  {formatPct(itemFeatures.change_1d_pct)}
                </span>
              </div>
              <div className="watch-row-foot">
                <ActionBadge action={item.latest_judgement?.action ?? item.latest_judgement?.output?.action} />
                <span>{formatConfidence(item.latest_judgement?.confidence)}</span>
              </div>
            </Link>
          );
        })}
        {items.length === 0 ? <p className="empty-text">データなし</p> : null}
      </div>
    </>
  );

  const detailPane =
    company && chart ? (
      <>
        <div className="main-action-panel">
          <CompanySearchForm initialCode={company.security_code} />
          <div className="main-action-buttons">
            <FetchGlobalNewsButton />
            <FetchCompanyDataButton securityCode={company.security_code} />
            <RunJudgementButton securityCode={company.security_code} />
            <ExternalPromptButton securityCode={company.security_code} />
          </div>
        </div>

        <div className="detail-panel-head">
          <div>
            <p className="eyebrow">{company.security_code}</p>
            <h2>{company.name}</h2>
            <span className="meta-line">{[company.market, company.sector, company.industry].filter(Boolean).join(" / ")}</span>
          </div>
          <div className="detail-head-actions">
            <MiniMetric label="終値" value={formatPrice(features.last_close ?? company.latest_price?.close)} />
            <MiniMetric label="前日比" value={formatPct(features.change_1d_pct)} tone={Number(features.change_1d_pct ?? 0) >= 0 ? "positive" : "negative"} />
          </div>
        </div>

        <div className="detail-board">
          <section className="panel company-area">
            <div className="section-title-row">
              <h2>会社・決算</h2>
              <Building2 size={18} aria-hidden="true" />
            </div>
            <CompanySnapshot snapshot={latestFinancial} />
          </section>

          <section className="panel chart-area">
            <div className="section-title-row">
              <h2>チャート</h2>
              <span className="small-pill">{timeframe === "1d" ? "日足" : "週足"}</span>
            </div>
            <ChartPanel bars={chart.bars} />
          </section>

          <section className="panel news-area">
            <div className="section-title-row">
              <h2>ニュース・開示・外部要因</h2>
              <Newspaper size={18} aria-hidden="true" />
            </div>
            <NewsList news={news} disclosures={disclosures} globalNews={globalNews} />
          </section>

          <section className="panel advice-area">
            <div className="section-title-row">
              <h2>LLMアドバイス</h2>
              <ActionBadge action={latest?.action ?? latest?.output?.action} />
            </div>
            <Advice judgement={latest} />
          </section>

          <section className="panel evidence-area">
            <div className="section-title-row">
              <h2>判断根拠</h2>
              <span className="small-pill">Context</span>
            </div>
            <JudgementEvidencePanel context={latestContext} />
          </section>

          <section className="panel settings-area">
            <div className="section-title-row">
              <h2>設定</h2>
              <SlidersHorizontal size={18} aria-hidden="true" />
            </div>
            <DashboardSettings securityCode={company.security_code} timeframe={timeframe} features={features} />
          </section>
        </div>
      </>
    ) : (
      <>
        <div className="main-action-panel">
          <CompanySearchForm initialCode={selectedCode} />
          <div className="main-action-buttons">
            <FetchGlobalNewsButton />
          </div>
        </div>
        <div className="panel empty-detail">
          <p className="empty-text">銘柄を選択してください</p>
        </div>
      </>
    );

  return <DashboardShell watchPane={watchPane} detailPane={detailPane} />;
}

function WatchlistSortLinks({
  sortMode,
  selectedCode,
  timeframe
}: {
  sortMode: SortMode;
  selectedCode?: string;
  timeframe: Timeframe;
}) {
  const selected = selectedCode ? `&securityCode=${encodeURIComponent(selectedCode)}` : "";
  return (
    <div className="segmented compact-sort">
      <Link href={`/?sort=code&timeframe=${timeframe}${selected}`} className={sortMode === "code" ? "active" : undefined}>
        コード順
      </Link>
      <Link
        href={`/?sort=recommendation&timeframe=${timeframe}${selected}`}
        className={sortMode === "recommendation" ? "active" : undefined}
      >
        推奨順
      </Link>
    </div>
  );
}

function sortWatchlistItems(items: WatchlistItem[], sortMode: SortMode) {
  if (sortMode === "code") {
    return [...items].sort((a, b) => a.security_code.localeCompare(b.security_code, "ja"));
  }
  return [...items].sort((a, b) => {
    const actionA = a.latest_judgement?.action ?? a.latest_judgement?.output?.action ?? "";
    const actionB = b.latest_judgement?.action ?? b.latest_judgement?.output?.action ?? "";
    const rankDiff = (actionRank[actionA] ?? 9) - (actionRank[actionB] ?? 9);
    if (rankDiff !== 0) {
      return rankDiff;
    }
    const confidenceDiff = Number(b.latest_judgement?.confidence ?? 0) - Number(a.latest_judgement?.confidence ?? 0);
    if (confidenceDiff !== 0) {
      return confidenceDiff;
    }
    return a.security_code.localeCompare(b.security_code, "ja");
  });
}

function MiniMetric({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="mini-metric">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function CompanySnapshot({ snapshot }: { snapshot?: FinancialSnapshot }) {
  if (!snapshot) {
    return <p className="empty-text">会社情報なし</p>;
  }
  const metrics = snapshot.metrics ?? {};
  const metricRows = [
    ["PER", metrics.per],
    ["PBR", metrics.pbr],
    ["ROE", metrics.roe],
    ["配当利回り", metrics.dividend_yield],
    ["EPS", metrics.eps],
    ["自己資本比率", metrics.equity_ratio]
  ] as const;
  return (
    <div className="company-snapshot">
      <div className="setting-grid company-metrics">
        {metricRows.map(([label, metric]) => (
          <SettingValue key={label} label={label} value={formatMetric(metric)} />
        ))}
      </div>
      <div className="company-summary">
        <span className="meta-line">
          {snapshot.as_of}
          {snapshot.next_earnings_date ? ` / 次回決算 ${snapshot.next_earnings_date}` : ""}
        </span>
        <p>{snapshot.summary ?? "-"}</p>
      </div>
    </div>
  );
}

function NewsList({
  news,
  disclosures,
  globalNews
}: {
  news: NewsArticle[];
  disclosures: Disclosure[];
  globalNews: GlobalNews[];
}) {
  if (news.length === 0 && disclosures.length === 0 && globalNews.length === 0) {
    return <p className="empty-text">ニュースなし</p>;
  }
  return (
    <div className="news-stack">
      <div className="compact-list">
        {news.map((item) => (
          <article className="compact-item" key={`news-${item.id}`}>
            <div className="compact-item-head">
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
              ) : (
                <strong>{item.title}</strong>
              )}
              <span>{[item.published_at, item.provider].filter(Boolean).join(" / ") || "-"}</span>
            </div>
            {item.summary ? <p>{item.summary}</p> : null}
          </article>
        ))}
      </div>
      {disclosures.length > 0 ? (
        <div className="disclosure-block">
          <div className="compact-label">
            <FileText size={15} aria-hidden="true" />
            <span>適時開示</span>
          </div>
          <div className="compact-list">
            {disclosures.map((item) => (
              <article className="compact-item" key={`disclosure-${item.id}`}>
                <div className="compact-item-head">
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noreferrer">
                      {item.title}
                    </a>
                  ) : (
                    <strong>{item.title}</strong>
                  )}
                  <span>{[item.published_at, item.document_type].filter(Boolean).join(" / ") || "-"}</span>
                </div>
                <p>{item.summary ?? "-"}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}
      {globalNews.length > 0 ? (
        <div className="disclosure-block">
          <div className="compact-label">
            <Newspaper size={15} aria-hidden="true" />
            <span>全体ニュース</span>
          </div>
          <div className="compact-list">
            {globalNews.map((item) => (
              <article className="compact-item" key={`global-${item.id}`}>
                <div className="compact-item-head">
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noreferrer">
                      {item.title}
                    </a>
                  ) : (
                    <strong>{item.title}</strong>
                  )}
                  <span>{[item.published_at, item.provider, summaryField(item.summary, "分類") ? `LLM分類: ${summaryField(item.summary, "分類")}` : null].filter(Boolean).join(" / ") || "-"}</span>
                </div>
                {item.summary ? <p>{item.summary}</p> : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Advice({ judgement }: { judgement?: Judgement }) {
  const output = judgement?.output;
  if (!output) {
    return <p className="empty-text">AI判断なし</p>;
  }
  return (
    <div className="advice-body">
      <p className="summary">{output.summary}</p>
      <div className="advice-columns">
        <AdviceList title="ポジティブ" items={output.positive_factors} />
        <AdviceList title="ネガティブ" items={output.negative_factors} />
        <AdviceList title="条件" items={[...output.entry_conditions, ...output.exit_conditions]} />
      </div>
      <span className="meta-line">confidence {formatConfidence(output.confidence)} / {judgement.model_provider}</span>
    </div>
  );
}

function AdviceList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="advice-list">
      <h3>{title}</h3>
      <ul>
        {items.slice(0, 3).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function DashboardSettings({
  securityCode,
  timeframe,
  features
}: {
  securityCode: string;
  timeframe: Timeframe;
  features: Record<string, string | number | boolean | null | undefined>;
}) {
  return (
    <div className="settings-stack">
      <div>
        <h3>足種</h3>
        <div className="segmented wide">
          <Link href={`/?securityCode=${securityCode}&timeframe=1d`} className={timeframe === "1d" ? "active" : undefined}>
            日足
          </Link>
          <Link href={`/?securityCode=${securityCode}&timeframe=1w`} className={timeframe === "1w" ? "active" : undefined}>
            週足
          </Link>
        </div>
      </div>
      <div className="setting-grid">
        <SettingValue label="MA5" value={formatPrice(Number(features.ma_5 ?? 0) || null)} />
        <SettingValue label="MA25" value={formatPrice(Number(features.ma_25 ?? 0) || null)} />
        <SettingValue label="MA75" value={formatPrice(Number(features.ma_75 ?? 0) || null)} />
        <SettingValue label="出来高倍率" value={features.volume_ratio_5d ? `${Number(features.volume_ratio_5d).toFixed(2)}x` : "-"} />
        <SettingValue label="短期" value={String(features.trend_short ?? "-")} />
        <SettingValue label="中期" value={String(features.trend_middle ?? "-")} />
      </div>
      <div className="toggle-list">
        <label>
          <input type="checkbox" checked readOnly />
          <span>移動平均</span>
        </label>
        <label>
          <input type="checkbox" checked readOnly />
          <span>出来高</span>
        </label>
        <label>
          <input type="checkbox" checked readOnly />
          <span>AI判断</span>
        </label>
      </div>
      <div className="setting-note">
        <Activity size={16} aria-hidden="true" />
        <span>Yahoo Finance / JPX400</span>
      </div>
    </div>
  );
}

function SettingValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatMetric(metric?: FinancialMetric | null) {
  if (!metric || metric.value === null || metric.value === undefined || metric.value === "") {
    return "-";
  }
  return `${metric.value}${metric.suffix ?? ""}`;
}

function summaryField(summary: string | null | undefined, label: string) {
  if (!summary) {
    return null;
  }
  const labels = "分類|要約|要点|注意|材料性|根拠";
  const match = summary.match(new RegExp(`(?:^|\\s)${label}[:：]\\s*(.*?)(?=\\s(?:${labels})[:：]|$)`));
  return match?.[1]?.trim() || null;
}
