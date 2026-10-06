"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import DataTable from "@/components/DataTable";
import ResultChart from "@/components/ResultChart";
import VoiceButton from "@/components/VoiceButton";
import { Button, Card, Spinner, inputCls } from "@/components/ui";
import { ApiError, runQuery } from "@/lib/api";
import type { QueryResponse } from "@/lib/types";

const SUGGESTIONS = [
  "What is the total revenue by product category?",
  "Who are the top 10 customers by total spend?",
  "How many orders were placed last month?",
  "What is the average rating per product category?",
  "Which products have never been ordered?",
  "What was the month-over-month revenue change in 2025?",
];

interface Turn { id: number; question: string; loading: boolean; response?: QueryResponse; error?: string }

function SqlPanel({ r }: { r: QueryResponse }) {
  return (
    <details className="group rounded-lg border border-slate-200 bg-slate-50">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-slate-700">Show SQL</summary>
      <div className="space-y-2 border-t border-slate-200 px-3 py-3">
        {r.explanation && <p className="text-sm text-slate-700"><span className="font-medium">Explanation:</span> {r.explanation}</p>}
        <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">{r.sql}</pre>
        {r.target_dialect && (
          <div>
            <p className="mb-1 text-xs font-medium text-slate-600">Rewritten for {r.target_dialect} (best effort, not executed):</p>
            <pre className="overflow-x-auto rounded-md bg-slate-800 p-3 text-xs leading-relaxed text-emerald-100">{r.transpiled_sql ?? "-- could not be transpiled"}</pre>
          </div>
        )}
        <p className="text-xs text-slate-500">
          {r.cached ? "⚡ from semantic cache · " : ""}{r.query_type} · {r.latency_ms.toFixed(0)} ms · {r.row_count} row{r.row_count === 1 ? "" : "s"}
          {Object.keys(r.stage_timings_ms).length > 0 && " · " + Object.entries(r.stage_timings_ms).map(([k, v]) => `${k} ${v.toFixed(0)}ms`).join(", ")}
        </p>
      </div>
    </details>
  );
}

function Answer({ turn, explain, onClarify }: { turn: Turn; explain: boolean; onClarify: (q: string, c: string) => void }) {
  if (turn.loading) return <Spinner label="Thinking — classifying, writing and checking the SQL…" />;
  if (turn.error) return <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{turn.error}</div>;
  const r = turn.response!;
  if (r.status === "unsupported")
    return <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><b>Read-only assistant.</b> {r.message}</div>;
  if (r.status !== "success")
    return (
      <div role="alert" className="space-y-1 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        <p>{r.message ?? "Something went wrong."}</p>
        {r.sql && <details><summary className="cursor-pointer text-xs">Show attempted SQL</summary><pre className="mt-1 overflow-x-auto text-xs">{r.sql}</pre></details>}
      </div>
    );
  return (
    <div className="space-y-3">
      <p className="text-slate-900">{r.nl_summary}</p>
      {r.ambiguities.map((a) => (
        <div key={a.term} className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
          <p><b>“{a.term}”</b> could mean more than one column. Did you mean:</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {a.candidates.map((c) => (
              <Button key={c} variant="ghost" className="!py-1 font-mono text-xs" onClick={() => onClarify(turn.question, `Interpret "${a.term}" as ${c}`)}>{c}</Button>
            ))}
          </div>
        </div>
      ))}
      {explain && r.explanation && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-900"><b>How this was answered:</b> {r.explanation}</div>
      )}
      {r.table && r.table.rows.length > 0 && (
        <div className="grid gap-3 lg:grid-cols-2">
          <DataTable columns={r.table.columns} rows={r.table.rows} />
          <ResultChart columns={r.table.columns} rows={r.table.rows} />
        </div>
      )}
      <SqlPanel r={r} />
    </div>
  );
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [explain, setExplain] = useState(false);
  const [dialect, setDialect] = useState("");
  const onVoice = useCallback((t: string) => setQuestion(t), []);
  const busy = turns.some((t) => t.loading);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns]);

  async function ask(q: string, clarification?: string) {
    const text = q.trim();
    if (!text || busy) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question: text, loading: true }]);
    setQuestion("");
    try {
      const response = await runQuery(text, clarification, dialect || undefined);
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, loading: false, response } : x)));
    } catch (e) {
      const error = e instanceof ApiError ? e.message : "Unexpected error. Please try again.";
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, loading: false, error } : x)));
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-2xl font-semibold">Ask your data anything</h1>
      <p className="mt-1 text-sm text-slate-600">Type a question in plain English. QueryMind writes the SQL, runs it read-only, and explains the result.</p>

      <div className="mt-5 space-y-5">
        {turns.length === 0 && (
          <Card>
            <p className="mb-3 text-sm font-medium text-slate-700">Try one of these</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => ask(s)} className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm text-indigo-800 hover:bg-indigo-100">{s}</button>
              ))}
            </div>
          </Card>
        )}
        {turns.map((t) => (
          <div key={t.id} className="space-y-2">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-sm text-white">{t.question}</div>
            <Card><Answer turn={t} explain={explain} onClarify={(q, c) => ask(q, c)} /></Card>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-slate-600">
        <label className="flex items-center gap-2"><input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} className="h-4 w-4 accent-violet-600" /> Explain mode</label>
        <label className="flex items-center gap-2">Also show SQL as
          <select value={dialect} onChange={(e) => setDialect(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
            <option value="">(same as database)</option><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option><option value="sqlite">SQLite</option>
          </select>
        </label>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); ask(question); }} className="sticky bottom-4 mt-6 flex gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={2000} aria-label="Your question"
          placeholder="e.g. Which country generated the most revenue in 2025?" className={`${inputCls} border-0 shadow-none focus:ring-0`} />
        <VoiceButton onText={onVoice} />
        <Button type="submit" disabled={busy || !question.trim()}>{busy ? "Working…" : "Ask"}</Button>
      </form>
    </div>
  );
}
