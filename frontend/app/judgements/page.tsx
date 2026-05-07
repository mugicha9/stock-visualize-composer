import Link from "next/link";
import { ActionBadge } from "@/components/ActionBadge";
import { apiGet } from "@/lib/api";
import { formatConfidence } from "@/lib/format";
import type { Judgement } from "@/lib/types";

export default async function JudgementsPage() {
  const judgements = await apiGet<Judgement[]>("/ai-judgements/latest?limit=100").catch(() => []);

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">AI</p>
          <h1>判断履歴</h1>
        </div>
      </section>
      <section className="section">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>判断日</th>
                <th>対象日</th>
                <th>銘柄</th>
                <th>アクション</th>
                <th>信頼度</th>
                <th>モデル</th>
                <th>要約</th>
                <th>根拠</th>
              </tr>
            </thead>
            <tbody>
              {judgements.map((item) => (
                <tr key={item.id}>
                  <td>{item.created_at.slice(0, 10)}</td>
                  <td>{item.target_date}</td>
                  <td>
                    <Link href={`/companies/${item.security_code}`} className="company-link">
                      {item.security_code} {item.company_name}
                    </Link>
                  </td>
                  <td>
                    <ActionBadge action={item.action ?? item.output?.action} />
                  </td>
                  <td className="number">{formatConfidence(item.confidence)}</td>
                  <td>{[item.model_provider, item.model_name].filter(Boolean).join(" / ")}</td>
                  <td>{item.output?.summary ?? "-"}</td>
                  <td>
                    <Link href={`/judgements/${item.id}`} className="company-link">
                      表示
                    </Link>
                  </td>
                </tr>
              ))}
              {judgements.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-cell">
                    データなし
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
