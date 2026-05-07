"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { apiPut } from "@/lib/api";

export type PromptItem = {
  key: string;
  label: string;
  value: string;
  updated_at?: string | null;
  source?: string | null;
};

export function PromptEditor({ prompts }: { prompts: PromptItem[] }) {
  const router = useRouter();
  const initialValues = useMemo(
    () => Object.fromEntries(prompts.map((item) => [item.key, item.value])),
    [prompts]
  );
  const [values, setValues] = useState<Record<string, string>>(() => ({ ...initialValues }));
  const [activeKey, setActiveKey] = useState(prompts[0]?.key ?? "");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValues({ ...initialValues });
  }, [initialValues]);

  useEffect(() => {
    if (!prompts.some((item) => item.key === activeKey)) {
      setActiveKey(prompts[0]?.key ?? "");
    }
  }, [activeKey, prompts]);

  const active = prompts.find((item) => item.key === activeKey) ?? prompts[0];
  const changedCount = prompts.filter((item) => (values[item.key] ?? "") !== (initialValues[item.key] ?? "")).length;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      const changed = prompts.filter((item) => (values[item.key] ?? "") !== (initialValues[item.key] ?? ""));
      await Promise.all(changed.map((item) => apiPut(`/prompts/${item.key}`, { value: values[item.key] ?? "" })));
      setMessage(changed.length === 0 ? "変更なし" : `${changed.length}件保存しました`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "プロンプト保存に失敗しました");
    } finally {
      setPending(false);
    }
  }

  if (prompts.length === 0 || !active) {
    return <p className="empty-text">編集可能なプロンプトなし</p>;
  }

  return (
    <form className="prompt-editor" onSubmit={onSubmit}>
      <div className="prompt-editor-nav" role="tablist" aria-label="LLM prompts">
        {prompts.map((item) => {
          const changed = (values[item.key] ?? "") !== (initialValues[item.key] ?? "");
          return (
            <button
              className={item.key === active.key ? "active" : undefined}
              key={item.key}
              type="button"
              onClick={() => setActiveKey(item.key)}
            >
              <span>{item.label}</span>
              <small>{changed ? "未保存" : item.source ?? item.key}</small>
            </button>
          );
        })}
      </div>
      <div className="prompt-editor-main">
        <label>
          <span>{active.label}</span>
          <textarea
            value={values[active.key] ?? ""}
            onChange={(event) => setValues({ ...values, [active.key]: event.target.value })}
          />
        </label>
        <div className="settings-editor-actions">
          <button className="icon-button primary" type="submit" disabled={pending}>
            <Save size={16} aria-hidden="true" />
            <span>{pending ? "保存中" : "プロンプトを保存"}</span>
          </button>
          <span className="setting-note">変更 {changedCount}件</span>
          {message ? <span className="bulk-message">{message}</span> : null}
          {error ? <span className="form-error inline-error">{error}</span> : null}
        </div>
      </div>
    </form>
  );
}
