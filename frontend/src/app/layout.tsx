import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Navbar from "@/components/Navbar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "UnchainedAPI — Uncensored LLM API Platform",
  description:
    "Access uncensored and abliterated LLM models via OpenAI-compatible API. Automatic model discovery, pay-per-token pricing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} ${jetbrains.variable} font-sans bg-grid scanlines min-h-screen`}>
        <div className="grain-overlay" />
        <Navbar />
        <main className="relative z-10">{children}</main>
      </body>
    </html>
  );
}
