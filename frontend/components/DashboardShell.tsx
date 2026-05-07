"use client";

import { ReactNode, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

export function DashboardShell({ watchPane, detailPane }: { watchPane: ReactNode; detailPane: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section className={collapsed ? "terminal-dashboard watch-collapsed" : "terminal-dashboard"}>
      <aside className="watch-pane" aria-label="銘柄リスト">
        <button
          className="watch-collapse-button"
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          title={collapsed ? "銘柄リストを開く" : "銘柄リストを閉じる"}
        >
          {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
          <span>{collapsed ? "開く" : "閉じる"}</span>
        </button>
        <div className="watch-pane-content">{watchPane}</div>
      </aside>
      <section className="detail-pane">{detailPane}</section>
    </section>
  );
}
