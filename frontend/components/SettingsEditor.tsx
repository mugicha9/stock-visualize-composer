"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { apiPut } from "@/lib/api";

type SettingItem = {
  key: string;
  value: string;
  updated_at: string;
};

const FIELDS = [
  { key: "default_llm_provider", label: "LLM Provider", type: "select", options: ["llama_cpp", "mock"] },
  { key: "llama_cpp_base_url", label: "llama.cpp API URL", type: "text" },
  { key: "llama_cpp_model_name", label: "モデル名/alias", type: "text" },
  { key: "llama_cpp_timeout_seconds", label: "判断Timeout秒", type: "number" },
  { key: "llama_cpp_temperature", label: "Temperature", type: "number", step: "0.1" },
  { key: "llama_cpp_top_p", label: "Top P", type: "number", step: "0.01" },
  { key: "llama_cpp_top_k", label: "Top K", type: "number" },
  { key: "llama_cpp_min_p", label: "Min P", type: "number", step: "0.01" },
  { key: "llama_cpp_presence_penalty", label: "Presence Penalty", type: "number", step: "0.1" },
  { key: "llama_cpp_repeat_penalty", label: "Repeat Penalty", type: "number", step: "0.1" },
  { key: "llm_judgement_max_attempts", label: "判断再試行回数", type: "number" },
  { key: "llm_grounding_auto_repair_enabled", label: "Grounding自動補正", type: "select", options: ["1", "0"] },
  { key: "context_packet_retention_per_company", label: "Context保存数/銘柄", type: "number" },
  { key: "llama_cpp_container_name", label: "Dockerコンテナ名", type: "text" },
  { key: "llama_cpp_image", label: "Docker Image", type: "text" },
  { key: "llama_cpp_docker_gpus", label: "Docker GPUs", type: "text" },
  { key: "llama_cpp_docker_restart", label: "Docker Restart", type: "text" },
  { key: "llama_cpp_host_models_dir", label: "HostモデルDir", type: "text" },
  { key: "llama_cpp_container_models_dir", label: "ContainerモデルDir", type: "text" },
  { key: "llama_cpp_model_file", label: "GGUFファイル名", type: "text" },
  { key: "llama_cpp_alias", label: "llama.cpp alias", type: "text" },
  { key: "llama_cpp_host", label: "llama.cpp Host", type: "text" },
  { key: "llama_cpp_port", label: "Host公開Port", type: "number" },
  { key: "llama_cpp_container_port", label: "Container Port", type: "number" },
  { key: "llama_cpp_context_length", label: "Context長", type: "number" },
  { key: "llama_cpp_n_parallel", label: "Parallel数", type: "number" },
  { key: "llama_cpp_ncmoe", label: "MoE experts", type: "number" },
  { key: "llama_cpp_gpu_layers", label: "GPU Layers", type: "text" },
  { key: "llama_cpp_no_mmap", label: "No mmap", type: "select", options: ["true", "false"] },
  { key: "llama_cpp_chat_template_kwargs", label: "Chat Template JSON", type: "textarea" },
  { key: "llama_cpp_reasoning", label: "Reasoning", type: "select", options: ["off", "auto", "on"] },
  { key: "llama_cpp_reasoning_budget", label: "Reasoning Budget", type: "number" },
  { key: "llama_cpp_docker_env_json", label: "Docker環境変数JSON", type: "textarea" },
  { key: "llama_cpp_extra_args", label: "追加llama.cpp引数", type: "textarea" },
  { key: "company_news_fetch_limit", label: "企業ニュース取得数", type: "number" },
  { key: "company_news_keyword_profile_enabled", label: "企業別キーワード", type: "select", options: ["1", "0"] },
  { key: "company_news_keyword_profile_refresh_days", label: "キーワード更新日数", type: "number" },
  { key: "company_news_relevance_min_score", label: "企業ニュース関連度下限", type: "number", step: "0.05" },
  { key: "company_news_keyword_fetch_multiplier", label: "ニュース候補取得倍率", type: "number" },
  { key: "global_news_fetch_limit_per_source", label: "全体ニュース取得数/RSS", type: "number" },
  { key: "llm_news_selection_max_company", label: "企業ニュース選別数", type: "number" },
  { key: "llm_news_selection_max_global", label: "全体ニュース選別数", type: "number" },
  { key: "news_summary_max_items", label: "取得時ニュース要約数", type: "number" },
  { key: "news_summary_timeout_seconds", label: "ニュース要約Timeout秒", type: "number" },
  { key: "news_summary_on_update", label: "一括更新時の要約", type: "select", options: ["0", "1"] },
  { key: "historical_news_lookback_days", label: "過去材料参照日数", type: "number" },
  { key: "historical_important_events_limit", label: "過去企業材料数", type: "number" },
  { key: "historical_global_events_limit", label: "過去全体材料数", type: "number" },
  { key: "material_assessment_enabled", label: "LLM材料評価", type: "select", options: ["1", "0"] },
  { key: "material_assessment_batch_size", label: "材料評価Batch数", type: "number" },
  { key: "material_assessment_max_items", label: "材料評価件数", type: "number" },
  { key: "material_assessment_timeout_seconds", label: "材料評価Timeout秒", type: "number" },
  { key: "disclosure_pdf_extract_on_update", label: "開示PDF抽出", type: "select", options: ["1", "0"] },
  { key: "disclosure_pdf_extract_limit", label: "開示PDF抽出数", type: "number" },
  { key: "disclosure_pdf_max_pages", label: "PDF抽出ページ数", type: "number" },
  { key: "disclosure_pdf_ocr_enabled", label: "PDF OCR", type: "select", options: ["0", "1"] }
] as const;

export function SettingsEditor({ settings }: { settings: SettingItem[] }) {
  const router = useRouter();
  const initialValues = useMemo(
    () => Object.fromEntries(settings.map((item) => [item.key, item.value])),
    [settings]
  );
  const [values, setValues] = useState<Record<string, string>>(() => ({ ...initialValues }));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValues({ ...initialValues });
  }, [initialValues]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      const changed = FIELDS.filter((field) => (values[field.key] ?? "") !== (initialValues[field.key] ?? ""));
      await Promise.all(changed.map((field) => apiPut(`/settings/${field.key}`, { value: values[field.key] ?? "" })));
      setMessage(changed.length === 0 ? "変更なし" : `${changed.length}件保存しました`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "設定保存に失敗しました");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="settings-editor" onSubmit={onSubmit}>
      <div className="settings-editor-grid">
        {FIELDS.map((field) => (
          <label key={field.key} className={field.type === "textarea" ? "wide-field" : undefined}>
            <span>{field.label}</span>
            {field.type === "select" ? (
              <select value={values[field.key] ?? ""} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : field.type === "textarea" ? (
              <textarea
                rows={4}
                value={values[field.key] ?? ""}
                onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}
              />
            ) : (
              <input
                type={field.type}
                step={"step" in field ? field.step : undefined}
                value={values[field.key] ?? ""}
                onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}
              />
            )}
          </label>
        ))}
      </div>
      <div className="settings-editor-actions">
        <button className="icon-button primary" type="submit" disabled={pending}>
          <Save size={16} aria-hidden="true" />
          <span>{pending ? "保存中" : "設定を保存"}</span>
        </button>
        {message ? <span className="bulk-message">{message}</span> : null}
        {error ? <span className="form-error inline-error">{error}</span> : null}
      </div>
    </form>
  );
}
