"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Globe2 } from "lucide-react";
import { apiPost } from "@/lib/api";

export function FetchGlobalNewsButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setPending(true);
    setError(null);
    try {
      await apiPost("/jobs/update-global-news", {});
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "全体情報の取得に失敗しました");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="button-stack">
      <button className="icon-button" type="button" disabled={pending} title="経済・政策・地政学など共有ニュースを取得" onClick={onClick}>
        <Globe2 size={16} aria-hidden="true" />
        <span>{pending ? "取得中" : "全体取得"}</span>
      </button>
      {error ? <span className="form-error inline-error">{error}</span> : null}
    </div>
  );
}
