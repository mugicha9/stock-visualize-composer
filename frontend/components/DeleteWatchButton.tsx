"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { apiDelete } from "@/lib/api";

export function DeleteWatchButton({ watchlistId }: { watchlistId: number }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function remove() {
    setPending(true);
    try {
      await apiDelete(`/watchlist/${watchlistId}`);
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  return (
    <button className="icon-only danger" type="button" onClick={remove} disabled={pending} title="削除">
      <Trash2 size={16} aria-hidden="true" />
    </button>
  );
}
