"use client";

import { useEffect, useState } from "react";
import { ClipboardCopy, FileInput, X } from "lucide-react";
import { apiGet } from "@/lib/api";
import type { ExternalAdvicePrompt } from "@/lib/types";

export function ExternalPromptButton({ securityCode }: { securityCode: string }) {
  const [pending, setPending] = useState(false);
  const [prompt, setPrompt] = useState<ExternalAdvicePrompt | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    if (prompt) {
      setPrompt(null);
      return;
    }
    setPending(true);
    setCopied(false);
    setError(null);
    try {
      setPrompt(await apiGet<ExternalAdvicePrompt>(`/companies/${securityCode}/ai-judgements/external-prompt`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "プロンプト生成に失敗しました");
    } finally {
      setPending(false);
    }
  }

  async function copyPrompt() {
    if (!prompt?.prompt) {
      return;
    }
    await navigator.clipboard.writeText(prompt.prompt);
    setCopied(true);
  }

  useEffect(() => {
    if (!prompt) {
      return;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setPrompt(null);
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [prompt]);

  return (
    <div className="button-stack prompt-button-stack">
      <button className="icon-button" type="button" onClick={generate} disabled={pending} title={prompt ? "外部AI用プロンプトを閉じる" : "外部AI用プロンプトを生成"}>
        <FileInput size={16} aria-hidden="true" />
        <span>{pending ? "生成中" : prompt ? "閉じる" : "外部AI"}</span>
      </button>
      {error ? <p className="form-error">{error}</p> : null}
      {prompt ? (
        <div className="prompt-popover">
          <div className="prompt-popover-head">
            <strong>外部AI用プロンプト</strong>
            <div className="prompt-popover-actions">
              <button className="icon-button" type="button" onClick={copyPrompt} title="プロンプトをコピー">
                <ClipboardCopy size={15} aria-hidden="true" />
                <span>{copied ? "コピー済み" : "コピー"}</span>
              </button>
              <button className="icon-only" type="button" onClick={() => setPrompt(null)} title="閉じる">
                <X size={16} aria-hidden="true" />
              </button>
            </div>
          </div>
          <textarea readOnly value={prompt.prompt} />
        </div>
      ) : null}
    </div>
  );
}
