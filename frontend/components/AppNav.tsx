"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, GitBranch, History, LineChart, Settings, Star } from "lucide-react";

const navItems = [
  { href: "/", label: "Watchlist", icon: Star },
  { href: "/backtests", label: "バックテスト", icon: LineChart },
  { href: "/pipeline", label: "Pipeline", icon: GitBranch },
  { href: "/judgements", label: "AI履歴", icon: History },
  { href: "/settings", label: "設定", icon: Settings }
];

export function AppNav() {
  const pathname = usePathname();
  return (
    <header className="app-header">
      <Link href="/" className="brand">
        <BarChart3 size={22} aria-hidden="true" />
        <span>Stock Visualize Composer</span>
      </Link>
      <nav className="nav-tabs" aria-label="Primary">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link key={item.href} href={item.href} className={active ? "nav-tab active" : "nav-tab"}>
              <Icon size={16} aria-hidden="true" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
