import Link from "next/link";
import { ActionBadge } from "@/components/ActionBadge";
import { JudgementEvidencePanel } from "@/components/JudgementEvidencePanel";
import { apiGet } from "@/lib/api";
import { formatConfidence } from "@/lib/format";
import type { JudgementContext } from "@/lib/types";

type Props = {
  params: {
    id: string;
  };
};

export default async function JudgementDetailPage({ params }: Props) {
  const context = await apiGet<JudgementContext>(`/ai-judgements/${params.id}/context`).catch(() => null);
  const judgement = context?.judgement;

  return (
    <>
      <Link href="/judgements" className="back-link">
        判断履歴へ戻る
      </Link>
      <section className="page-head detail-head">
        <div>
          <p className="eyebrow">AI Evidence</p>
          <h1>
            {judgement?.security_code ?? "-"} {judgement?.company_name ?? ""}
          </h1>
          <span className="subline">
            {judgement ? `${judgement.created_at} / ${judgement.model_provider}${judgement.model_name ? ` / ${judgement.model_name}` : ""}` : "データなし"}
          </span>
        </div>
        {judgement ? (
          <div className="detail-head-actions">
            <ActionBadge action={judgement.output?.action ?? judgement.action} />
            <div className="mini-metric">
              <span>信頼度</span>
              <strong>{formatConfidence(judgement.output?.confidence ?? judgement.confidence)}</strong>
            </div>
          </div>
        ) : null}
      </section>
      <section className="section">
        <JudgementEvidencePanel context={context} />
      </section>
    </>
  );
}
