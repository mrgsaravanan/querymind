import type { Metadata } from "next";
import type { ReactNode } from "react";
import Nav from "@/components/Nav";
import { ToastProvider } from "@/components/Toast";
import "./globals.css";

export const metadata: Metadata = { title: "QueryMind AI", description: "Ask your data questions in plain English" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ToastProvider>
          <Nav />
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
        </ToastProvider>
      </body>
    </html>
  );
}
