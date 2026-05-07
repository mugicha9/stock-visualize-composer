"use client";

import { FormEvent, useMemo, useState } from "react";
import { Database, Play, RotateCcw, Search } from "lucide-react";
import { ActionBadge } from "@/components/ActionBadge";
import { apiPost } from "@/lib/api";
import { formatConfidence, formatNumber, formatPrice } from "@/lib/format";
import type {
  BacktestInterval,
  BacktestPeriodInfoRequest,
  BacktestPeriodInfoResponse,
  BacktestProvider,
  BacktestRequest,
  BacktestResponse,
  WatchlistItem
} from "@/lib/types";

type Props = {
  items: WatchlistItem[];
};

export function BacktestRunner({ items }: Props) {
  const defaultCode = items[0]?.security_code ?? "";
  const [securityCode, setSecurityCode] = useState(defaultCode);
  const [startDate, setStartDate] = useState(defaultStartDate());
  const [endDate, setEndDate] = useState("");
  const [interval, setInterval] = useState<BacktestInterval>("1mo");
  const [provider, setProvider] = useState<BacktestProvider>("mock");
  const [maxSteps, setMaxSteps] = useState(260);
  const [pending, setPending] = useState(false);
  const [infoPending, setInfoPending] = useState(false);
  const [persistInfo, setPersistInfo] = useState(true);
  const [infoResult, setInfoResult] = useState<BacktestPeriodInfoResponse | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const companyOptions = useMemo(
    () => items.map((item) => `${item.security_code} ${item.name}`).sort((a, b) => a.localeCompare(b, "ja")),
    [items]
  );

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!securityCode.trim()) {
      setError("銘柄コードを入力してください");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const boundedMaxSteps = Number.isFinite(maxSteps) ? Math.min(520, Math.max(1, maxSteps)) : 260;
      const payload: BacktestRequest = {
        security_code: securityCode.trim(),
        start_date: startDate || null,
        end_date: endDate || null,
        interval,
        provider,
        max_steps: boundedMaxSteps
      };
      const response = await apiPost<BacktestResponse>("/backtests/run", payload);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "バックテストに失敗しました");
    } finally {
      setPending(false);
    }
  }

  function resetDates() {
    setStartDate(defaultStartDate());
    setEndDate("");
  }

  async function fetchPeriodInfo() {
    if (!securityCode.trim()) {
      setError("銘柄コードを入力してください");
      return;
    }
    setInfoPending(true);
    setError(null);
    try {
      const payload: BacktestPeriodInfoRequest = {
        security_code: securityCode.trim(),
        start_date: startDate || null,
        end_date: endDate || null,
        persist: persistInfo,
        include_news: true,
        include_disclosures: true,
        include_external_factors: true,
        news_limit: 80,
        disclosure_limit: 80,
        external_factor_limit: 80
      };
      const response = await apiPost<BacktestPeriodInfoResponse>("/backtests/fetch-period-info", payload);
      setInfoResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "期間情報の取得に失敗しました");
    } finally {
      setInfoPending(false);
    }
  }

  return (
    <div className="backtest-page">
      <section className="page-head detail-head">
        <div>
          <p className="eyebrow">Backtest</p>
          <h1>バックテスト</h1>
          <span className="subline">判断日の情報だけで売買し、翌営業日始値で約定します</span>
        </div>
      </section>

      <form className="panel backtest-form" onSubmit={run}>
        <div className="backtest-form-grid">
          <label>
            <span>銘柄コード</span>
            <input
              list="backtest-symbols"
              value={securityCode}
              onChange={(event) => setSecurityCode(event.target.value.split(" ")[0])}
              placeholder="7203"
            />
            <datalist id="backtest-symbols">
              {companyOptions.map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
          </label>
          <label>
            <span>開始日</span>
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </label>
          <label>
            <span>終了日</span>
            <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </label>
          <label>
            <span>判定間隔</span>
            <select value={interval} onChange={(event) => setInterval(event.target.value as BacktestInterval)}>
              <option value="1w">1週間ごと</option>
              <option value="2w">2週間ごと</option>
              <option value="1mo">1か月ごと</option>
              <option value="1d">1日ごと</option>
            </select>
          </label>
          <label>
            <span>AI</span>
            <select value={provider} onChange={(event) => setProvider(event.target.value as BacktestProvider)}>
              <option value="mock">mock</option>
              <option value="llama_cpp">llama.cpp</option>
            </select>
          </label>
          <label>
            <span>最大判定回数</span>
            <input
              type="number"
              min={1}
              max={520}
              value={maxSteps}
              onChange={(event) => setMaxSteps(Number(event.target.value))}
            />
          </label>
        </div>
        <div className="backtest-actions">
          <label className="inline-checkbox">
            <input type="checkbox" checked={persistInfo} onChange={(event) => setPersistInfo(event.target.checked)} />
            <span>DB保存</span>
          </label>
          <button className="icon-button" type="button" onClick={fetchPeriodInfo} disabled={pending || infoPending} title="バックテスト期間のニュース、開示、外部要因を取得">
            {persistInfo ? <Database size={16} aria-hidden="true" /> : <Search size={16} aria-hidden="true" />}
            <span>{infoPending ? "取得中" : "期間情報取得"}</span>
          </button>
          <button className="icon-button" type="button" onClick={resetDates} disabled={pending} title="期間を初期値に戻す">
            <RotateCcw size={16} aria-hidden="true" />
            <span>期間リセット</span>
          </button>
          <button className="icon-button primary" type="submit" disabled={pending} title="バックテストを実行">
            <Play size={16} aria-hidden="true" />
            <span>{pending ? "実行中" : "実行"}</span>
          </button>
        </div>
        {error ? <p className="form-error">{error}</p> : null}
      </form>

      {infoResult ? <PeriodInfoSummary result={infoResult} /> : null}
      {result ? <BacktestResult result={result} /> : <EmptyBacktest />}
    </div>
  );
}

function PeriodInfoSummary({ result }: { result: BacktestPeriodInfoResponse }) {
  const coverage = result.coverage_after;
  const labels: Record<string, string> = {
    disclosures: "開示",
    news_articles: "ニュース",
    global_news: "全体ニュース",
    company_financials: "財務"
  };
  return (
    <section className="panel period-info-panel">
      <div className="section-title-row">
        <h2>期間情報</h2>
        <span className="meta-line">
          {result.period.start_date} から {result.period.end_date} / {result.persisted ? "保存済み" : "プレビュー"}
        </span>
      </div>
      <div className="setting-grid period-info-grid">
        {Object.entries(labels).map(([key, label]) => (
          <div key={key}>
            <span>{label}</span>
            <strong>{formatCoverage(coverage[key])}</strong>
          </div>
        ))}
      </div>
      {result.source_notes[0] ? <p className="meta-line">{result.source_notes[0]}</p> : null}
    </section>
  );
}

function BacktestResult({ result }: { result: BacktestResponse }) {
  return (
    <div className="backtest-result">
      <section className="panel backtest-summary-panel">
        <div className="section-title-row">
          <div>
            <h2>
              {result.company.security_code} {result.company.name}
            </h2>
            <span className="meta-line">
              {result.config.start_date} から {result.config.end_date} / {formatInterval(result.config.interval)} / {result.config.provider}
              {result.config.model_name ? ` / ${result.config.model_name}` : ""}
            </span>
          </div>
          {result.config.truncated ? <span className="small-pill">上限で打ち切り</span> : null}
        </div>
        <div className="metric-strip backtest-metrics">
          <Metric label="戦略" value={formatSignedPct(result.summary.total_return_pct)} tone={tone(result.summary.total_return_pct)} />
          <Metric label="保有" value={formatSignedPct(result.summary.buy_and_hold_return_pct)} tone={tone(result.summary.buy_and_hold_return_pct)} />
          <Metric label="超過" value={formatSignedPct(result.summary.excess_return_pct)} tone={tone(result.summary.excess_return_pct)} />
          <Metric label="最大DD" value={formatSignedPct(result.summary.max_drawdown_pct)} tone="negative" />
          <Metric label="勝率" value={formatPlainPct(result.summary.win_rate_pct)} />
          <Metric label="売買数" value={`${result.summary.trade_count}`} />
        </div>
        <EquityChart points={result.equity_curve} />
      </section>

      <section className="panel">
        <div className="section-title-row">
          <h2>未来情報ガード</h2>
        </div>
        <div className="guard-list">
          {Object.values(result.leakage_guard).map((item) => (
            <p key={item}>{item}</p>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-title-row">
          <h2>売買履歴</h2>
          <span className="meta-line">平均 {formatSignedPct(result.summary.average_trade_return_pct)}</span>
        </div>
        <div className="table-wrap">
          <table className="data-table backtest-table">
            <thead>
              <tr>
                <th>買付日</th>
                <th>売却日</th>
                <th>買付根拠</th>
                <th>売却根拠</th>
                <th className="number">買付</th>
                <th className="number">売却</th>
                <th className="number">損益</th>
              </tr>
            </thead>
            <tbody>
              {result.trades.map((trade, index) => (
                <tr key={`${trade.entry_date}-${trade.exit_date}-${index}`}>
                  <td>{trade.entry_date}</td>
                  <td>{trade.exit_date}</td>
                  <td>
                    <ActionBadge action={trade.entry_signal} />
                  </td>
                  <td>
                    <ActionBadge action={trade.exit_signal} />
                  </td>
                  <td className="number">{formatPrice(trade.entry_price)}</td>
                  <td className="number">{formatPrice(trade.exit_price)}</td>
                  <td className={`number ${tone(trade.return_pct)}`}>{formatSignedPct(trade.return_pct)}</td>
                </tr>
              ))}
              {result.trades.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    売買なし
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="section-title-row">
          <h2>判定履歴</h2>
          <span className="meta-line">{result.decisions.length}件</span>
        </div>
        <div className="table-wrap">
          <table className="data-table backtest-table wide">
            <thead>
              <tr>
                <th>判断日</th>
                <th>アクション</th>
                <th className="number">信頼度</th>
                <th className="number">終値</th>
                <th>約定</th>
                <th className="number">評価</th>
                <th>データ</th>
                <th>要約</th>
              </tr>
            </thead>
            <tbody>
              {result.decisions.map((decision) => (
                <tr key={decision.date}>
                  <td>{decision.date}</td>
                  <td>
                    <ActionBadge action={decision.action} />
                  </td>
                  <td className="number">{formatConfidence(decision.confidence)}</td>
                  <td className="number">{formatPrice(decision.price_close)}</td>
                  <td>{formatExecution(decision.executed_action, decision.next_execution_date, decision.next_execution_price)}</td>
                  <td className={`number ${tone(decision.equity_pct)}`}>{formatSignedPct(decision.equity_pct)}</td>
                  <td>{formatDataCounts(decision.data_counts, decision.data_warnings)}</td>
                  <td>{decision.summary}</td>
                </tr>
              ))}
              {result.decisions.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-cell">
                    データなし
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {result.errors.length > 0 ? <p className="form-error">判断生成エラー {result.errors.length}件</p> : null}
      </section>
    </div>
  );
}

function EmptyBacktest() {
  return (
    <section className="panel empty-detail">
      <p className="empty-text">条件を指定して実行してください</p>
    </section>
  );
}

function Metric({ label, value, tone: toneName }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={toneName}>{value}</strong>
    </div>
  );
}

function EquityChart({ points }: { points: BacktestResponse["equity_curve"] }) {
  const width = 720;
  const height = 180;
  if (points.length < 2) {
    return <div className="chart-empty compact">チャートなし</div>;
  }
  const values = points.map((point) => point.normalized_value);
  const minValue = Math.min(1, ...values);
  const maxValue = Math.max(1, ...values);
  const range = maxValue - minValue || 1;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((point.normalized_value - minValue) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const zeroY = height - ((1 - minValue) / range) * height;

  return (
    <div className="equity-chart" aria-label="バックテスト損益曲線">
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <line x1="0" x2={width} y1={zeroY} y2={zeroY} className="equity-zero" />
        <polyline points={path} className="equity-line" />
      </svg>
      <div className="equity-chart-meta">
        <span>{points[0]?.date}</span>
        <span>{points[points.length - 1]?.date}</span>
      </div>
    </div>
  );
}

function formatExecution(action: string | null | undefined, date: string, price?: number | null) {
  if (!action) {
    return "-";
  }
  return `${action} ${date} ${formatPrice(price)}`;
}

function formatDataCounts(counts: Record<string, number>, warnings: string[]) {
  const parts = [
    `開示${counts.recent_disclosures ?? 0}`,
    `企業ニュース${counts.selected_company_news ?? 0}`,
    `全体ニュース${counts.selected_global_news ?? 0}`,
    `財務${counts.has_financial_snapshot ? "あり" : "なし"}`
  ];
  return warnings.length > 0 ? `${parts.join(" / ")} / ${warnings.join(", ")}` : parts.join(" / ");
}

function formatCoverage(value?: { available: number; earliest_date?: string | null; latest_date?: string | null }) {
  if (!value) {
    return "0件";
  }
  const range = value.earliest_date && value.latest_date ? ` / ${value.earliest_date}〜${value.latest_date}` : "";
  return `${value.available}件${range}`;
}

function formatInterval(interval: BacktestInterval) {
  const labels: Record<BacktestInterval, string> = {
    "1d": "1日ごと",
    "1w": "1週間ごと",
    "2w": "2週間ごと",
    "1mo": "1か月ごと"
  };
  return labels[interval];
}

function formatSignedPct(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${value >= 0 ? "+" : ""}${formatNumber(value, 2)}%`;
}

function formatPlainPct(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${formatNumber(value, 1)}%`;
}

function tone(value?: number | null): "positive" | "negative" | undefined {
  if (value === undefined || value === null || Number.isNaN(value) || value === 0) {
    return undefined;
  }
  return value > 0 ? "positive" : "negative";
}

function defaultStartDate() {
  const value = new Date();
  value.setFullYear(value.getFullYear() - 1);
  return value.toISOString().slice(0, 10);
}
