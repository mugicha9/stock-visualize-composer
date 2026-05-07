import type { Action } from "@/lib/types";

const labels: Record<Action, string> = {
  BUY: "BUY",
  WATCH_BUY: "WATCH_BUY",
  NO_TRADE: "NO_TRADE",
  WATCH_SELL: "WATCH_SELL",
  SELL: "SELL",
  INSUFFICIENT_DATA: "INSUFFICIENT_DATA"
};

export function ActionBadge({ action }: { action?: Action | null }) {
  if (!action) return <span className="badge muted">未実行</span>;
  return <span className={`badge action-${action}`}>{labels[action]}</span>;
}
