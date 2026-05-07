"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { FilePlus } from "lucide-react";
import { apiPost } from "@/lib/api";

export function DisclosureForm({ securityCode }: { securityCode: string }) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [publishedAt, setPublishedAt] = useState("");
  const [summary, setSummary] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    try {
      await apiPost(`/companies/${securityCode}/disclosures`, {
        title,
        published_at: publishedAt || undefined,
        summary: summary || undefined,
        document_type: "manual",
        source: "manual"
      });
      setTitle("");
      setPublishedAt("");
      setSummary("");
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="stack-form" onSubmit={onSubmit}>
      <label>
        <span>開示タイトル</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)} required />
      </label>
      <label>
        <span>公開日</span>
        <input type="date" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} />
      </label>
      <label>
        <span>要約</span>
        <textarea value={summary} onChange={(event) => setSummary(event.target.value)} rows={3} />
      </label>
      <button className="icon-button" type="submit" disabled={pending} title="開示を登録">
        <FilePlus size={16} aria-hidden="true" />
        <span>{pending ? "登録中" : "登録"}</span>
      </button>
    </form>
  );
}
