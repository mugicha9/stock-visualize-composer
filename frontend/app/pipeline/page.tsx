import { PipelineExplorer } from "@/components/PipelineExplorer";
import { PromptEditor, type PromptItem } from "@/components/PromptEditor";
import { SettingsEditor } from "@/components/SettingsEditor";
import { apiGet } from "@/lib/api";

type SettingsResponse = {
  settings: {
    key: string;
    value: string;
    updated_at: string;
  }[];
};

type PromptsResponse = {
  prompts: PromptItem[];
};

export default async function PipelinePage() {
  const data = await apiGet<SettingsResponse>("/settings").catch(() => ({ settings: [] }));
  const promptData = await apiGet<PromptsResponse>("/prompts").catch((): PromptsResponse => ({ prompts: [] }));

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">LLM Pipeline</p>
          <h1>判断パイプライン</h1>
          <span className="subline">取得、選別、要約、Signal Card、Context Packet、最終判断の流れ</span>
        </div>
      </section>
      <section className="section">
        <PipelineExplorer />
      </section>
      <section className="section">
        <div className="section-title-row">
          <h2>プロンプト編集</h2>
        </div>
        <PromptEditor prompts={promptData.prompts} />
      </section>
      <section className="section">
        <div className="section-title-row">
          <h2>調整可能な設定</h2>
        </div>
        <SettingsEditor settings={data.settings} />
      </section>
    </>
  );
}
