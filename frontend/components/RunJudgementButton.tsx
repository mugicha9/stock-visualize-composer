"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Play } from "lucide-react";
import { apiPost } from "@/lib/api";

export function RunJudgementButton({ securityCode }: { securityCode: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setPending(true);
    setError(null);
    try {
      await apiPost(`/companies/${securityCode}/ai-judgements/run`, {});
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI判断に失敗しました");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="button-stack">
      <button className="icon-button primary" type="button" onClick={run} disabled={pending} title="中長期AI判断を実行">
        <Play size={16} aria-hidden="true" />
        <span>{pending ? "実行中" : "AI判断"}</span>
      </button>
      {error ? <p className="form-error">{error}</p> : null}
    </div>
  );
}
