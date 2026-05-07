"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { DownloadCloud, Plus } from "lucide-react";
import { apiPost } from "@/lib/api";

export function AddWatchForm() {
  const router = useRouter();
  const [securityCode, setSecurityCode] = useState("");
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [pendingMode, setPendingMode] = useState<"add" | "fetch" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const mode = submitter?.value === "fetch" ? "fetch" : "add";
    setPending(true);
    setPendingMode(mode);
    setError(null);
    try {
      await apiPost("/watchlist", {
        security_code: securityCode.trim(),
        name: name.trim() || undefined,
        fetch_prices: mode === "fetch",
        fetch_context: mode === "fetch",
        summarize_news: mode === "fetch",
        price_range: "1y"
      });
      setSecurityCode("");
      setName("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登録に失敗しました");
    } finally {
      setPending(false);
      setPendingMode(null);
    }
  }

  return (
    <form className="inline-form" onSubmit={onSubmit}>
      <label>
        <span>コード</span>
        <input
          value={securityCode}
          onChange={(event) => setSecurityCode(event.target.value)}
          placeholder="7203"
          minLength={4}
          maxLength={5}
          required
        />
      </label>
      <label>
        <span>会社名</span>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="任意" />
      </label>
      <button className="icon-button" type="submit" name="mode" value="add" disabled={pending} title="ウォッチリストに追加">
        <Plus size={16} aria-hidden="true" />
        <span>追加</span>
      </button>
      <button className="icon-button primary" type="submit" name="mode" value="fetch" disabled={pending} title="追加してデータ取得">
        <DownloadCloud size={16} aria-hidden="true" />
        <span>{pending && pendingMode === "fetch" ? "取得中" : "追加して取得"}</span>
      </button>
      {error ? <p className="form-error">{error}</p> : null}
    </form>
  );
}
