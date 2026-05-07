import { Layers, Newspaper } from "lucide-react";
import { ActionBadge } from "@/components/ActionBadge";
import { formatConfidence } from "@/lib/format";
import type { ContextSummaryBlock, JudgementContext, JudgementSourceItem, SignalCard } from "@/lib/types";

export function JudgementEvidencePanel({ context }: { context?: JudgementContext | null }) {
  if (!context) {
    return <p className="empty-text">判断根拠なし</p>;
  }

  const packet = context.context_packet;
  const aggregate = packet.aggregated_signal ?? {};
  const cards = packet.signal_cards ?? [];
  const newsItems = context.source_items.news_digest_items ?? [];
  const output = context.judgement.output;
  const usedSignalIds = new Set(output?.used_signal_ids ?? []);
  const grounding = context.judgement.model_options?.grounding as
    | { repair_mode?: string; issues?: string[]; issues_before_fallback?: string[]; attempts?: number }
    | undefined;

  return (
    <div className="evidence-panel">
      <div className="evidence-summary-head">
        <div>
          <p className="eyebrow">Judgement Context</p>
          <h3>{packet.as_of ?? context.judgement.target_date} 時点の入力</h3>
        </div>
        <div className="evidence-head-actions">
          <ActionBadge action={output?.action ?? context.judgement.action} />
          <span className="meta-line">{formatConfidence(output?.confidence ?? context.judgement.confidence)}</span>
        </div>
      </div>

      <div className="setting-grid evidence-metrics">
        <EvidenceMetric label="総合バイアス" value={String(aggregate.overall_bias ?? "-")} />
        <EvidenceMetric label="総合スコア" value={formatScore(aggregate.weighted_score)} />
        <EvidenceMetric label="Signal数" value={String(aggregate.signal_count ?? cards.length)} />
        <EvidenceMetric label="Technical" value={formatScore(aggregate.technical_score)} />
        <EvidenceMetric label="Fundamental" value={formatScore(aggregate.fundamental_score)} />
        <EvidenceMetric label="News/Market" value={formatScore(aggregate.news_score)} />
      </div>

      {grounding ? <GroundingStatus grounding={grounding} loadedFromPacket={context.loaded_from_context_packet} /> : null}

      <CompanyProfile profile={packet.company_profile} />

      <div className="context-summary-grid">
        <ContextSummary title="テクニカル" summary={packet.technical_summary} />
        <ContextSummary title="ファンダメンタル" summary={packet.fundamental_summary} />
        <ContextSummary title="ニュース・外部要因" summary={packet.news_summary} />
      </div>

      <section className="evidence-subsection">
        <div className="compact-label">
          <Layers size={15} aria-hidden="true" />
          <span>使用Signal Card</span>
        </div>
        <div className="signal-card-list">
          {cards.map((card, index) => (
            <SignalCardView
              card={card}
              key={card.signal_id || `${card.source_type}-${index}`}
              open={index < 3 || usedSignalIds.has(card.signal_id) || Boolean(card.used_by_judgement)}
              used={usedSignalIds.has(card.signal_id) || Boolean(card.used_by_judgement)}
            />
          ))}
          {cards.length === 0 ? <p className="empty-text">Signal Cardなし</p> : null}
        </div>
      </section>

      <section className="evidence-subsection">
        <div className="compact-label">
          <Newspaper size={15} aria-hidden="true" />
          <span>判断時に参照したニュース・開示</span>
        </div>
        <SourceItems items={newsItems} />
      </section>
    </div>
  );
}

function GroundingStatus({
  grounding,
  loadedFromPacket
}: {
  grounding: { repair_mode?: string; issues?: string[]; issues_before_fallback?: string[]; attempts?: number };
  loadedFromPacket?: boolean;
}) {
  const repaired = grounding.repair_mode && grounding.repair_mode !== "none";
  return (
    <div className={repaired ? "grounding-status repaired" : "grounding-status"}>
      <span>{loadedFromPacket ? "保存済みContext Packet" : "再構築Context Packet"}</span>
      <strong>{repaired ? `Grounding補正: ${grounding.repair_mode}` : "Grounding補正なし"}</strong>
      <small>
        {[
          grounding.attempts !== undefined ? `attempts ${grounding.attempts}` : null,
          grounding.issues_before_fallback?.length ? `issues: ${grounding.issues_before_fallback.join(", ")}` : null
        ]
          .filter(Boolean)
          .join(" / ")}
      </small>
    </div>
  );
}

function CompanyProfile({ profile }: { profile?: JudgementContext["context_packet"]["company_profile"] }) {
  if (!profile) {
    return null;
  }
  const businessTerms = profile.business_terms?.filter(Boolean) ?? [];
  const materialTerms = profile.material_terms?.filter(Boolean) ?? [];
  if (businessTerms.length === 0 && !profile.financial_summary) {
    return null;
  }
  return (
    <article className="company-profile-strip">
      <div>
        <span>企業プロファイル</span>
        <strong>{[profile.sector, profile.industry].filter(Boolean).join(" / ") || "業種未設定"}</strong>
      </div>
      {businessTerms.length ? (
        <p>
          <b>主力/関連テーマ</b>
          {businessTerms.slice(0, 8).join(" / ")}
        </p>
      ) : null}
      {materialTerms.length ? (
        <p>
          <b>重視材料</b>
          {materialTerms.slice(0, 8).join(" / ")}
        </p>
      ) : null}
      {profile.financial_summary ? <p>{profile.financial_summary}</p> : null}
    </article>
  );
}

function EvidenceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ContextSummary({ title, summary }: { title: string; summary?: ContextSummaryBlock }) {
  return (
    <article className="context-summary-card">
      <div className="context-summary-card-head">
        <strong>{title}</strong>
        <span>{formatScore(summary?.direction_score)} / impact {formatScore(summary?.impact_score)}</span>
      </div>
      <p>{summary?.summary || "該当なし"}</p>
      {summary?.risk_notes?.length ? (
        <ul>
          {summary.risk_notes.slice(0, 3).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function SignalCardView({ card, open, used }: { card: SignalCard; open: boolean; used: boolean }) {
  return (
    <details className={`signal-card signal-${card.source_type}${used ? " used" : ""}`} open={open}>
      <summary>
        <span className={`signal-dot direction-${card.direction}`} />
        <strong>{sourceLabel(card.source_type)}</strong>
        {used ? <span className="used-signal-badge">USED</span> : null}
        <span>{card.direction}</span>
        <span>impact {formatScore(card.impact_score)}</span>
        <span>{card.published_at ?? "-"}</span>
      </summary>
      <div className="signal-card-body">
        <p>{card.summary}</p>
        {card.topic ? <span className="summary-chip">LLM分類: {card.topic}</span> : null}
        {card.material_assessment ? (
          <span className="summary-chip">
            材料評価: {card.material_assessment.provider ?? "-"} / relevance {formatScore(card.material_assessment.company_relevance)}
          </span>
        ) : null}
        <SignalList title="根拠" items={card.evidence ?? []} />
        <SignalList title="リスク" items={card.risk_notes ?? []} />
      </div>
    </details>
  );
}

function SignalList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="signal-list">
      <span>{title}</span>
      <ul>
        {items.slice(0, 5).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function SourceItems({ items }: { items: JudgementSourceItem[] }) {
  if (items.length === 0) {
    return <p className="empty-text">参照ニュースなし</p>;
  }
  return (
    <div className="source-item-list">
      {items.slice(0, 12).map((item, index) => (
        <SourceItem item={item} index={index} key={`${item.type ?? "source"}-${item.id ?? index}-${item.title ?? index}`} />
      ))}
    </div>
  );
}

function SourceItem({ item, index }: { item: JudgementSourceItem; index: number }) {
  const parsed = parseStructuredSummary(item.summary);
  return (
    <article className="source-item">
      <div className="source-item-head">
        <strong>{item.title ?? "-"}</strong>
        <span>{[item.date ?? item.information_date ?? item.published_at, item.type, item.provider ?? item.source].filter(Boolean).join(" / ")}</span>
      </div>
      {parsed.summary ? <p>{parsed.summary}</p> : item.summary ? <p>{item.summary}</p> : null}
      {parsed.points.length || parsed.risks.length ? (
        <div className="source-summary-detail">
          {parsed.points.length ? (
            <div>
              <span>要点</span>
              <ul>
                {parsed.points.map((point) => (
                  <li key={`${index}-point-${point}`}>{point}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {parsed.risks.length ? (
            <div>
              <span>注意</span>
              <ul>
                {parsed.risks.map((risk) => (
                  <li key={`${index}-risk-${risk}`}>{risk}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="factor-tags">
        {[
          parsed.topic ? `LLM分類: ${parsed.topic}` : null,
          parsed.materiality ? `材料性: ${parsed.materiality}` : null,
          parsed.basis ? `根拠: ${parsed.basis}` : null,
          item.relevance_score !== undefined && item.relevance_score !== null ? `relevance: ${formatScore(item.relevance_score)}` : null,
          item.selection_reason ? `reason: ${item.selection_reason}` : null
        ]
          .filter(Boolean)
          .join(" / ")}
      </div>
    </article>
  );
}

function sourceLabel(sourceType: string) {
  const labels: Record<string, string> = {
    technical: "テクニカル",
    fundamental: "ファンダメンタル",
    news: "企業ニュース・開示",
    market: "全体ニュース"
  };
  return labels[sourceType] ?? sourceType;
}

function formatScore(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(2);
}

function parseStructuredSummary(summary?: string | null) {
  const topic = summaryField(summary, "分類");
  const summaryText = summaryField(summary, "要約");
  const points = splitSummaryList(summaryField(summary, "要点"));
  const risks = splitSummaryList(summaryField(summary, "注意"));
  const materiality = summaryField(summary, "材料性");
  const basis = summaryField(summary, "根拠");
  return { topic, summary: summaryText, points, risks, materiality, basis };
}

function summaryField(summary: string | null | undefined, label: string) {
  if (!summary) {
    return null;
  }
  const labels = "分類|要約|要点|注意|材料性|根拠";
  const match = summary.match(new RegExp(`(?:^|\\s)${label}[:：]\\s*(.*?)(?=\\s(?:${labels})[:：]|$)`));
  return match?.[1]?.trim() || null;
}

function splitSummaryList(value: string | null) {
  if (!value) {
    return [];
  }
  return value
    .split(" / ")
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 4);
}
