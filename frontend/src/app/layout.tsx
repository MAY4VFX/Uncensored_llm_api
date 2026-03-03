import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Navbar from "@/components/Navbar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "UnchainedAPI — Uncensored LLM API Platform",
  description:
    "Access uncensored and abliterated LLM models via OpenAI-compatible API. Automatic model discovery, pay-per-token pricing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-grid min-h-screen`}>
        <Navbar />
        <main>{children}</main>
      </body>
    </html>
  );
}
