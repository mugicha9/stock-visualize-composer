import { BacktestRunner } from "@/components/BacktestRunner";
import { apiGet } from "@/lib/api";
import type { WatchlistItem } from "@/lib/types";

export default async function BacktestsPage() {
  const items = await apiGet<WatchlistItem[]>("/watchlist?list_name=JPX400").catch(() => []);

  return <BacktestRunner items={items} />;
}
