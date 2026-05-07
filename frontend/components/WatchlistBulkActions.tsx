"use client";

import { useState } from "react";
import { Bot, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";

type BulkAction = "update" | "judge";

export function WatchlistBulkActions({ listName }: { listName: string }) {
  const router = useRouter();
  const [pending, setPending] = useState<BulkAction | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(action: BulkAction) {
    setPending(action);
    setMessage(null);
    setError(null);
    try {
      const path = action === "update" ? "/jobs/update-watchlist-data" : "/jobs/run-short-term-judgements";
      const result = await apiPost<{ status: string; count: number; error_count?: number; errors?: Record<string, unknown> }>(path, {
        list_name: listName,
        range: "1y"
      });
      const failed = result.error_count ?? Object.keys(result.errors ?? {}).length;
      setMessage(`${result.count}件完了${failed ? ` / エラー${failed}件` : ""}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "一括処理に失敗しました");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="bulk-actions">
      <button className="icon-button" type="button" disabled={pending !== null} onClick={() => run("update")} title="ウォッチリスト全銘柄の企業別データを更新">
        <RefreshCw size={16} aria-hidden="true" />
        <span>{pending === "update" ? "更新中" : "企業全更新"}</span>
      </button>
      <button className="icon-button primary" type="button" disabled={pending !== null} onClick={() => run("judge")} title="ウォッチリスト全銘柄のAI判断を実行">
        <Bot size={16} aria-hidden="true" />
        <span>{pending === "judge" ? "実行中" : "全AI判断"}</span>
      </button>
      {message ? <p className="bulk-message">{message}</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
    </div>
  );
}
