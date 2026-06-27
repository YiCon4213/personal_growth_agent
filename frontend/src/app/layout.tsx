import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Personal Growth Agent",
  description: "Unified chat frontend for the personal growth multi-agent platform"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
