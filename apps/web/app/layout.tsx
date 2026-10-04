import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "KY-JARVIS Command Center",
  description: "Local-first governed work orchestration",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-TW">
      <body>{children}</body>
    </html>
  );
}
