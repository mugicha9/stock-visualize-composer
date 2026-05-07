"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { apiPost } from "@/lib/api";

export function FetchCompanyDataButton({ securityCode }: { securityCode: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setPending(true);
    setError(null);
    try {
      await apiPost(`/companies/${securityCode}/fetch-data`, {
        price_range: "1y",
        include_prices: true,
        include_financials: true,
        include_disclosures: true,
        include_news: true,
        summarize_news: true,
        include_external_factors: false
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "取得に失敗しました");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="button-stack">
      <button className="icon-button" type="button" disabled={pending} title="選択企業の株価・会社情報・開示・企業ニュースを取得" onClick={onClick}>
        <RefreshCw size={16} aria-hidden="true" />
        <span>{pending ? "取得中" : "企業取得"}</span>
      </button>
      {error ? <span className="form-error inline-error">{error}</span> : null}
    </div>
  );
}
