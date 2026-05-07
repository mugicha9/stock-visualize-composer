import type { Metadata } from "next";
import { AppNav } from "@/components/AppNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Visualize Composer",
  description: "Japanese stock short-term decision support for local use"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <AppNav />
        <main className="workspace">{children}</main>
      </body>
    </html>
  );
}
