import { apiGet } from "@/lib/api";
import { SettingsEditor } from "@/components/SettingsEditor";

type SettingsResponse = {
  config_path?: string;
  settings: {
    key: string;
    value: string;
    updated_at: string;
  }[];
};

export default async function SettingsPage() {
  const data = await apiGet<SettingsResponse>("/settings").catch((): SettingsResponse => ({ settings: [] }));

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">Local</p>
          <h1>設定</h1>
          {data.config_path ? <span className="subline">Config: {data.config_path}</span> : null}
        </div>
      </section>
      <section className="section">
        <div className="section-title-row">
          <h2>LLM / ニュース取得</h2>
        </div>
        <SettingsEditor settings={data.settings} />
      </section>
      <section className="section">
        <div className="table-wrap narrow">
          <table className="data-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Value</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.settings.map((item) => (
                <tr key={item.key}>
                  <td className="mono">{item.key}</td>
                  <td className="mono">{item.value}</td>
                  <td>{item.updated_at.slice(0, 19)}</td>
                </tr>
              ))}
              {data.settings.length === 0 ? (
                <tr>
                  <td colSpan={3} className="empty-cell">
                    データなし
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
