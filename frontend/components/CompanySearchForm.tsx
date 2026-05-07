"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

export function CompanySearchForm({ initialCode }: { initialCode?: string }) {
  const router = useRouter();
  const [securityCode, setSecurityCode] = useState(initialCode ?? "");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = securityCode.trim();
    if (!code) {
      return;
    }
    router.push(`/?securityCode=${encodeURIComponent(code)}`);
  }

  return (
    <form className="main-search-form" onSubmit={onSubmit}>
      <label>
        <span>銘柄検索</span>
        <input
          value={securityCode}
          onChange={(event) => setSecurityCode(event.target.value)}
          placeholder="7203"
          minLength={4}
          maxLength={5}
          inputMode="numeric"
          required
        />
      </label>
      <button className="icon-button primary" type="submit" title="銘柄を検索">
        <Search size={16} aria-hidden="true" />
        <span>検索</span>
      </button>
    </form>
  );
}
