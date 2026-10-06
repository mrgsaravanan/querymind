"use client";
import { useCallback, useEffect, useState } from "react";
import { Button, Card, ErrorBox, PageHeader, Spinner, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import type { QueryLogEntry } from "@/lib/types";

const STATUSES = ["success", "unsupported", "validation_failed", "execution_error", "error"];
const badge: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-800", unsupported: "bg-amber-100 text-amber-800",
  validation_failed: "bg-red-100 text-red-800", execution_error: "bg-red-100 text-red-800", error: "bg-red-100 text-red-800",
};

export default function LogsPage() {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<QueryLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const params = useCallback(() => {
    const p: Record<string, string> = {};
    if (status) p.status = status;
    if (q.trim()) p.q = q.trim();
    if (from) p.from = `${from}T00:00:00`;
    if (to) p.to = `${to}T23:59:59`;
    return p;
  }, [status, q, from, to]);

  const load = useCallback(() => {
    setError(null);
    api.logs({ ...params(), limit: "200" }).then(setRows).catch((e) => setError(e.message));
  }, [params]);
  useEffect(() => { load(); }, [status, from, to]); // text filter applies on submit

  return (
    <>
      <PageHeader title="Query Logs" subtitle="Every question, the SQL that ran, outcome, latency and row count."
        actions={<a href={api.logsExportUrl(params())} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Export CSV</a>} />
      <Card className="mb-4">
        <form className="grid gap-3 md:grid-cols-5" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <input className={`${inputCls} md:col-span-2`} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search question or SQL…" aria-label="Search text" />
          <input type="date" className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
          <input type="date" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
          <div className="md:col-span-5 flex gap-2">
            <Button type="submit">Apply</Button>
            <Button type="button" variant="ghost" onClick={() => { setStatus(""); setQ(""); setFrom(""); setTo(""); setTimeout(load, 0); }}>Reset</Button>
          </div>
        </form>
      </Card>
      {error && <ErrorBox message={error} onRetry={load} />}
      {!rows && !error && <Spinner />}
      {rows && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Time (UTC)</th><th className="px-3 py-2">Question</th><th className="px-3 py-2">SQL</th>
                <th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Latency</th><th className="px-3 py-2 text-right">Rows</th></tr>
            </thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">No log entries match.</td></tr>}
              {rows.map((r) => (
                <>
                  <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)} className="cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50">
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{r.created_at.replace("T", " ").slice(0, 19)}</td>
                    <td className="max-w-xs px-3 py-2">{r.question}</td>
                    <td className="max-w-md px-3 py-2 font-mono text-xs text-slate-600"><div className="line-clamp-2">{r.sql ?? "—"}</div></td>
                    <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge[r.status] ?? "bg-slate-100"}`}>{r.status}</span></td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{r.latency_ms.toFixed(0)} ms</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.row_count}</td>
                  </tr>
                  {open === r.id && (
                    <tr key={`${r.id}-d`} className="bg-slate-50">
                      <td colSpan={6} className="space-y-1 px-4 py-3 text-xs">
                        {r.error && <p className="text-red-700"><b>Error:</b> {r.error}</p>}
                        {r.sql && <pre className="overflow-x-auto rounded bg-slate-900 p-2 text-slate-100">{r.sql}</pre>}
                        <p className="text-slate-500">type: {r.query_type ?? "—"} · stages: {Object.entries(r.stage_timings_ms).map(([k, v]) => `${k} ${v.toFixed(0)}ms`).join(", ") || "—"}</p>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
